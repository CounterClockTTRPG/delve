import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { NeedsToken } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT, type Translate } from "../i18n";
import SettingText from "./SettingText";
import {
  acceptProposal,
  editProposal,
  listProposals,
  rejectProposal,
  settingKeys,
  type Proposal,
  type ProposalEdit,
} from "./api";
import styles from "./Setting.module.css";

const newestFirst = (a: Proposal, b: Proposal) => b.created_at.localeCompare(a.created_at) || b.id - a.id;

function kindLabel(t: Translate, proposal: Proposal): string {
  if (proposal.kind === "edit") return t("setting.proposals.kind.edit", { title: proposal.title });
  return t(`setting.proposals.kind.${proposal.kind}`);
}

/**
 * The DM's pending proposals to this setting, newest first. Each holds in its own campaign already; accepting one
 * makes it an addition (or a fact) of every campaign. It can be edited before, or rejected.
 */
export default function ProposalsTab({ settingId }: { settingId: string }) {
  const t = useT();
  const proposals = useQuery({ queryKey: settingKeys.proposals(settingId), queryFn: () => listProposals(settingId) });
  const failed = proposals.error && !(proposals.error instanceof NeedsToken) ? proposals.error : null;
  const pageHref = (title: string) => `/settings/${encodeURIComponent(settingId)}/pages/${encodeURIComponent(title)}`;

  return (
    <div className={styles.proposals}>
      {failed && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: failed.message })}
        </p>
      )}
      {proposals.data &&
        (proposals.data.length === 0 ? (
          <p className="placeholder">{t("setting.proposals.empty")}</p>
        ) : (
          <ul className="rows">
            {[...proposals.data].sort(newestFirst).map((p) => (
              <ProposalRow key={p.id} settingId={settingId} proposal={p} pageHref={pageHref} />
            ))}
          </ul>
        ))}
    </div>
  );
}

function ProposalRow({ settingId, proposal, pageHref }: { settingId: string; proposal: Proposal; pageHref: (title: string) => string }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  // A decided proposal leaves the list at once; the setting's counts, pages and facts change with it.
  const decided = () => {
    client.setQueryData<Proposal[]>(settingKeys.proposals(settingId), (old) => old?.filter((p) => p.id !== proposal.id));
    return client.invalidateQueries({ queryKey: settingKeys.one(settingId) });
  };
  const edited = (p: Proposal) => {
    client.setQueryData<Proposal[]>(settingKeys.proposals(settingId), (old) => old?.map((o) => (o.id === p.id ? p : o)));
  };
  const accept = useMutation({
    // An edit is saved first, so what is accepted is what the organiser sees.
    mutationFn: async (edit?: ProposalEdit) => {
      if (edit) edited(await editProposal(settingId, proposal.id, edit));
      return acceptProposal(settingId, proposal.id);
    },
    onSuccess: decided,
  });
  const save = useMutation({
    mutationFn: (edit: ProposalEdit) => editProposal(settingId, proposal.id, edit),
    onSuccess: (p) => {
      edited(p);
      setEditing(false);
    },
  });
  const reject = useMutation({ mutationFn: () => rejectProposal(settingId, proposal.id), onSuccess: decided });
  const busy = accept.isPending || save.isPending || reject.isPending;
  const failed = [accept.error, save.error, reject.error].find((e) => e && !(e instanceof NeedsToken));

  const askReject = async () => {
    const sure = await confirm({
      title: t("setting.proposals.rejectConfirm", { kind: kindLabel(t, proposal) }),
      confirm: t("setting.proposals.reject"),
      danger: true,
    });
    if (sure) reject.mutate();
  };

  return (
    <li className={`row ${styles.proposal}`}>
      <div className={styles.tags}>
        <span className="tag">{kindLabel(t, proposal)}</span>
        {proposal.kind === "page" && <strong>{proposal.title}</strong>}
        {proposal.kind === "fact" && proposal.category && <span className="row-meta">{proposal.category}</span>}
        {proposal.dm_only && <span className="dm-only-mark">{t("setting.dmOnly")}</span>}
        <span className="row-meta">
          {t("setting.proposals.from")} <Link to={`/campaigns/${encodeURIComponent(proposal.campaign_id)}`}>{proposal.campaign_title}</Link>
        </span>
      </div>

      {editing ? (
        <ProposalForm
          proposal={proposal}
          busy={busy}
          onSave={(edit) => save.mutate(edit)}
          onAccept={(edit) => accept.mutate(edit)}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <SettingText text={proposal.text} pageHref={pageHref} dmMarked />
          <div className="actions">
            <button type="button" className="primary" disabled={busy} onClick={() => accept.mutate(undefined)}>
              {t("setting.proposals.accept")}
            </button>
            <button type="button" disabled={busy} onClick={() => setEditing(true)}>
              {t("setting.proposals.edit")}
            </button>
            <button type="button" className="danger" disabled={busy} onClick={askReject}>
              {t("setting.proposals.reject")}
            </button>
          </div>
        </>
      )}

      {failed && (
        <p role="alert" className="notice error">
          {t("setting.saveFailed", { error: failed.message })}
        </p>
      )}
    </li>
  );
}

/** A proposal opened in place: its title (a page's) or category (a fact's), its text and DM only; Save, or Accept. */
function ProposalForm({
  proposal,
  busy,
  onSave,
  onAccept,
  onCancel,
}: {
  proposal: Proposal;
  busy: boolean;
  onSave: (edit: ProposalEdit) => void;
  onAccept: (edit: ProposalEdit) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const id = useId();
  const isFact = proposal.kind === "fact";
  const [title, setTitle] = useState(proposal.title);
  const [category, setCategory] = useState(proposal.category);
  const [text, setText] = useState(proposal.text);
  const [dmOnly, setDmOnly] = useState(proposal.dm_only);
  const edit = (): ProposalEdit =>
    isFact ? { text, category: category.trim(), dm_only: dmOnly } : { title: title.trim(), text, dm_only: dmOnly };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSave(edit());
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      {isFact ? (
        <div className="field">
          <label htmlFor={`${id}-category`}>{t("setting.facts.category")}</label>
          <input id={`${id}-category`} value={category} onChange={(e) => setCategory(e.target.value)} />
        </div>
      ) : (
        <div className="field">
          <label htmlFor={`${id}-title`}>{t("setting.form.title")}</label>
          <input id={`${id}-title`} required value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
      )}
      <div className="field">
        <label htmlFor={`${id}-text`}>{t("setting.form.text")}</label>
        <textarea id={`${id}-text`} rows={8} required value={text} onChange={(e) => setText(e.target.value)} />
        {!isFact && <span className="hint">{t("setting.dmSectionHint")}</span>}
      </div>
      <label className="check">
        <input type="checkbox" checked={dmOnly} onChange={(e) => setDmOnly(e.target.checked)} />
        {t("setting.form.dmOnly")}
      </label>
      <div className="actions">
        <button type="button" className="primary" disabled={busy} onClick={() => onAccept(edit())}>
          {t("setting.proposals.accept")}
        </button>
        <button type="submit" disabled={busy}>
          {t("setting.form.save")}
        </button>
        <button type="button" onClick={onCancel}>
          {t("dialog.cancel")}
        </button>
      </div>
    </form>
  );
}
