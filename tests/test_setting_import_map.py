"""`delve setting import-map` (settings plan Task 10, decision 15): a thin client of the running Delve. It streams the
picture to `POST /api/conversions/worldmap` with the owner token, and the job, run by the server, leaves the setting's
map in review. Delve is the app on uvicorn on a free loopback socket; Claude is `FakeDM` answering from the synthetic
picture's truth, and the OCR is the fake one."""

import asyncio
import io
import re
from dataclasses import replace

import uvicorn

from delve.__main__ import main
from delve.config import Config
from delve.conversions import wait
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.storage import open_storage
from delve.web.app import create_app
from delve.web.routes.conversions import conversions
from tests.conversions.test_worldmap_job import _answer
from tests.maps.geo.pictures import fake_look, fake_ocr, hex_map
from tests.web.conftest import make_registries
from tests.web.test_events import free_socket


def test_the_command_leaves_a_map_in_review(tmp_path, monkeypatch, capsys):
    synthetic = hex_map()
    picture = tmp_path / "flanaess.png"
    out = io.BytesIO()
    synthetic.image.save(out, "PNG")
    picture.write_bytes(out.getvalue())

    config = Config(data_dir=tmp_path / "data")
    monkeypatch.setenv("DELVE_DATA_DIR", str(config.data_dir))
    storage = open_storage(config)
    look = fake_look(synthetic.truth)
    dm = Registry()
    dm.register(
        FAKE_DM_CAPABILITIES,
        lambda: FakeDM([], vision_handler=lambda prompt, image, media_type: _answer(look, prompt, image, media_type)),
    )
    registries = replace(make_registries(), dm=dm)
    app = create_app(config, storage, registries)
    conversions(app).picture_ocr = fake_ocr(synthetic.truth)

    async def scenario():
        sock = free_socket()
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        serving = asyncio.ensure_future(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(30):
                while not server.started:
                    await asyncio.sleep(0.01)
                command = ["setting", "import-map", "greyhawk", str(picture), "--name", "flanaess"]
                command += ["--title", "The Flanaess", "--distance", "30", "--units", "miles", "--port", str(port)]
                code = await asyncio.to_thread(main, command)
                printed = capsys.readouterr().out
                [id_] = re.findall(r"\(conversion (\S+)\)", printed)
                return code, printed, port, await wait(conversions(app), id_)
        finally:
            server.should_exit = True
            await serving
            sock.close()

    try:
        code, printed, port, done = asyncio.run(scenario())
        assert code == 0
        assert printed.strip() == (
            f"Reading flanaess for greyhawk in the background (conversion {done.id}). Review it at "
            f"http://localhost:{port}/world-maps/setting/greyhawk/flanaess/review"
        )
        assert done.status == "done", done.error
        assert done.target == {"setting_id": "greyhawk", "name": "flanaess", "title": "The Flanaess"}
        world_map = storage.setting_maps.get("greyhawk", "flanaess")
        assert (world_map.status, world_map.title) == ("review", "The Flanaess")
        assert world_map.picture == done.result["picture"]
    finally:
        storage.close()
