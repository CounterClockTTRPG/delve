import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Pin } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ago } from "../components/ago";
import { useLanguage, useT } from "../i18n";
import { attachPicture, boardKeys, getZone, startTopic, type Zone } from "./api";
import { useReader } from "./BoardFrame";
import PostEditor from "./PostEditor";
import { authorName, sayError } from "./show";
import ZoneSettings, { ZonePeople } from "./ZoneSettings";

// `/board/:zoneId` (DEL-297): the zone's topics, pinned first, then the most recently written, each with who started
// it, its replies, its last post and whether it is new to the reader; New topic for who may write there, and Log in
// to post for a visitor on a zone where accounts write. Settings for who may manage the zone, People for who may
// moderate a zone with members.

/** The longest topic title (the server's limit). */
const TITLE_LIMIT = 120;

export default function ZonePage() {
  const t = useT();
  const language = useLanguage();
  const { zoneId = "" } = useParams();
  const { signedIn } = useReader();
  const shown = useQuery({ queryKey: boardKeys.zone(zoneId), queryFn: () => getZone(zoneId) });
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const [dialog, setDialog] = useState<"settings" | "people" | null>(null);

  if (shown.isPending)
    return (
      <main className="board-main">
        <p className="board-quiet">{t("board.loading")}</p>
      </main>
    );
  if (shown.isError)
    return (
      <main className="board-main">
        <Crumbs />
        <p className="notice error" role="alert">
          {t("board.noZone")}
        </p>
      </main>
    );
  const { zone, topics } = shown.data;
  return (
    <main className="board-main">
      <Crumbs zone={zone} />
      <header className="board-page-head">
        <h1>{zone.name}</h1>
        <div className="board-actions">
          {zone.rights.moderate && (zone.read === "members" || zone.write === "members") && (
            <button type="button" onClick={() => setDialog("people")}>
              {t("board.people")}
            </button>
          )}
          {zone.rights.manage && (
            <button type="button" onClick={() => setDialog("settings")}>
              {t("board.settings")}
            </button>
          )}
          {zone.rights.write && !starting && (
            <button type="button" className="primary" onClick={() => setStarting(true)}>
              {t("board.newTopic")}
            </button>
          )}
          {!signedIn && zone.write === "accounts" && (
            <a className="button-like" href="/login">
              {t("board.logInToPost")}
            </a>
          )}
        </div>
      </header>
      {zone.description && <p className="board-lede">{zone.description}</p>}
      {dialog === "settings" && (
        // The zone page lists all of the zone's topics (the server doesn't page them), so this count is exact.
        <ZoneSettings zone={zone} wide={zone.rights.manage_wide} topics={topics.length} onDone={() => setDialog(null)} onRemoved={() => navigate("/board")} />
      )}
      {dialog === "people" && <ZonePeople zone={zone} onDone={() => setDialog(null)} />}
      {starting && <NewTopic zone={zone} onCancel={() => setStarting(false)} />}
      {topics.length === 0 ? (
        <p className="board-quiet">{t("board.noTopics")}</p>
      ) : (
        <ul className="board-topics">
          {topics.map((topic) => (
            <li key={topic.id} className="board-topic">
              <div className="board-topic-title">
                {topic.pinned && <Pin size={14} className="board-mark" role="img" aria-label={t("board.pinned")} />}
                {topic.locked && <Lock size={14} className="board-mark" role="img" aria-label={t("board.locked")} />}
                <Link to={`/board/${encodeURIComponent(zone.id)}/${encodeURIComponent(topic.id)}`}>{topic.title}</Link>
                {topic.new && <span className="board-pill">{t("board.new")}</span>}
              </div>
              <p className="board-meta">
                <span>{t("board.startedBy", { name: authorName(t, topic.author) })}</span>
                <span>{t("board.replies", { count: String(Math.max(0, topic.posts - 1)) })}</span>
                <span>
                  {t("board.lastPost", { name: authorName(t, topic.last_author), when: ago(topic.last_post_at, language) })}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

/** Board › the zone (› the topic): the way back up. */
export function Crumbs({ zone, topic }: { zone?: Pick<Zone, "id" | "name">; topic?: string }) {
  const t = useT();
  return (
    <nav className="board-crumb" aria-label={t("board.crumb")}>
      <Link to="/board">{t("board.title")}</Link>
      {zone && (
        <>
          <span aria-hidden="true"> › </span>
          {topic ? <Link to={`/board/${encodeURIComponent(zone.id)}`}>{zone.name}</Link> : <span>{zone.name}</span>}
        </>
      )}
      {topic && (
        <>
          <span aria-hidden="true"> › </span>
          <span>{topic}</span>
        </>
      )}
    </nav>
  );
}

/** A new topic: its title and first post (with a picture, where the zone takes them); the topic opens once it is made. */
function NewTopic({ zone, onCancel }: { zone: Zone; onCancel: () => void }) {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [untitled, setUntitled] = useState(false);
  const [follow, setFollow] = useState(false);
  const start = useMutation({
    mutationFn: async ({ text, picture }: { text: string; picture: File | null }) => {
      const made = await startTopic(zone.id, title.trim(), text, follow);
      // The topic is made: a picture refused is said on its page, not here.
      let pictureError: string | null = null;
      if (picture) await attachPicture(made.post.id, picture).catch((error: unknown) => (pictureError = sayError(error)));
      return { topicId: made.topic.id, pictureError };
    },
    onSuccess: ({ topicId, pictureError }) => {
      void client.invalidateQueries({ queryKey: boardKeys.all });
      navigate(`/board/${encodeURIComponent(zone.id)}/${encodeURIComponent(topicId)}`, { state: { pictureError } });
    },
  });
  return (
    <section className="board-new-topic" aria-label={t("board.newTopic")}>
      <label className="board-field">
        <span>{t("board.topicTitle")}</span>
        <input value={title} maxLength={TITLE_LIMIT} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <PostEditor
        pictures={zone.pictures}
        busy={start.isPending}
        submitLabel={t("board.startTopic")}
        onCancel={onCancel}
        follow={{ checked: follow, onChange: setFollow }}
        onSubmit={(text, picture) => {
          setUntitled(!title.trim());
          if (title.trim()) start.mutate({ text, picture });
        }}
      />
      {untitled && !title.trim() && (
        <p className="notice error" role="alert">
          {t("board.titleFirst")}
        </p>
      )}
      {start.isError && (
        <p className="notice error" role="alert">
          {sayError(start.error)}
        </p>
      )}
    </section>
  );
}
