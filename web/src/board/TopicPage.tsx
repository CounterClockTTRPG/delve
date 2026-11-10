import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Pin } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import Lightbox from "../components/Lightbox";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT, type MessageKey } from "../i18n";
import { useMailEnabled } from "../mail/api";
import Avatar from "../profile/Avatar";
import {
  attachPicture,
  boardKeys,
  deletePost,
  deleteTopic,
  editPost,
  followTopic,
  getTopic,
  postAvatarUrl,
  postPictureUrl,
  reply,
  setTopic,
  takeDownPicture,
  unfollowTopic,
  type Author,
  type Post,
  type Zone,
} from "./api";
import { useReader } from "./BoardFrame";
import { quoteOf, renderPost } from "./markdown";
import PostEditor, { type Insert } from "./PostEditor";
import { authorName, postTime, sayError } from "./show";
import { Crumbs } from "./ZonePage";

// `/board/:zoneId/:topicId` (DEL-297): a topic as a modern thread (layout B): each post with its author's face, name,
// badges and time above it, the text the full width beneath, its picture to enlarge, and what the reader may do with
// it. It opens at the first page with something the reader hasn't read, scrolled to that post, and keeps that page
// (`?page=`) while new posts come in. The reply box is at the foot for who may write; a locked topic says so, and a
// visitor is asked to log in. While Delve sends email, a signed-in reader may follow the topic (DEL-314): Follow and
// Stop following by the title, and "Email me about replies" with a reply until they follow it.

/** How many posts a page holds (the server's `POST_PAGE`). */
const POST_PAGE = 30;

const BADGES: Record<string, MessageKey> = {
  organiser: "board.badge.organiser",
  moderator: "board.badge.moderator",
  host: "board.badge.host",
  cohost: "board.badge.cohost",
};

export default function TopicPage() {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const confirm = useConfirm();
  const { topicId = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const asked = Number(search.get("page"));
  const page = Number.isInteger(asked) && asked >= 1 ? asked : undefined;
  const shown = useQuery({ queryKey: boardKeys.topic(topicId, page), queryFn: () => getTopic(topicId, page), staleTime: 30_000 });
  const [insert, setInsert] = useState<Insert | undefined>(undefined);
  const [replyKey, setReplyKey] = useState(0);
  const [error, setError] = useState<string | null>((location.state as { pictureError?: string } | null)?.pictureError ?? null);
  const replyBox = useRef<HTMLDivElement>(null);
  const scrollTo = useRef<string | null>(null);
  const [followReply, setFollowReply] = useState(false);
  const mailEnabled = useMailEnabled();
  const { signedIn } = useReader();

  // Opened without a page: the server's pick becomes the address's, so new posts coming in don't move the reader on.
  const data = shown.data;
  useEffect(() => {
    if (page !== undefined || !data) return;
    scrollTo.current = data.first_unread_post;
    client.setQueryData(boardKeys.topic(topicId, data.page), data);
    setSearch((current) => new URLSearchParams({ ...Object.fromEntries(current), page: String(data.page) }), { replace: true });
  }, [client, data, page, setSearch, topicId]);
  useEffect(() => {
    if (page === undefined || !data || !scrollTo.current) return;
    document.getElementById(`post-${scrollTo.current}`)?.scrollIntoView?.({ block: "start" });
    scrollTo.current = null;
  }, [data, page]);

  // The box empties, and the reader goes to the last page, where the reply is.
  const sendReply = useReply(topicId, (pictureError) => {
    setReplyKey((n) => n + 1);
    setError(pictureError);
    const posts = shown.data?.topic.posts ?? 0;
    goTo(Math.max(1, Math.ceil((posts + 1) / POST_PAGE)));
  });
  const goTo = (next: number) => setSearch((current) => new URLSearchParams({ ...Object.fromEntries(current), page: String(next) }));
  const changed = () => client.invalidateQueries({ queryKey: boardKeys.all });
  const act = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onMutate: () => setError(null),
    onSuccess: () => void changed(),
    onError: (failed) => setError(sayError(failed)),
  });

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
          {t("board.noTopic")}
        </p>
      </main>
    );

  const { zone, topic, posts, pages } = shown.data;
  const at = shown.data.page;
  const mayReply = zone.rights.write && (!topic.locked || zone.rights.moderate);
  const following = topic.following ?? false;
  const mayFollow = signedIn && (mailEnabled || following);

  const quote = (post: Post) => {
    setInsert((last) => ({ text: quoteOf(authorName(t, post.author), post.text), n: (last?.n ?? 0) + 1 }));
    replyBox.current?.scrollIntoView?.({ block: "nearest" });
  };
  const toReply = () => {
    const box = replyBox.current?.querySelector("textarea");
    box?.scrollIntoView?.({ block: "nearest" });
    box?.focus();
  };
  const removeTopic = async () => {
    const sure = await confirm({ title: t("board.deleteTopicConfirm", { title: topic.title }), confirm: t("board.deleteTopic"), danger: true });
    if (!sure) return;
    act.mutate(async () => {
      await deleteTopic(topic.id);
      navigate(`/board/${encodeURIComponent(zone.id)}`);
    });
  };

  return (
    <main className="board-main board-thread">
      <Crumbs zone={zone} topic={topic.title} />
      <header className="board-page-head">
        <h1>
          {topic.pinned && <Pin size={18} className="board-mark" role="img" aria-label={t("board.pinned")} />}
          {topic.locked && <Lock size={18} className="board-mark" role="img" aria-label={t("board.locked")} />}
          {topic.title}
        </h1>
        {mayFollow && (
          <div className="board-actions">
            <button
              type="button"
              aria-pressed={following}
              disabled={act.isPending}
              onClick={() => act.mutate(() => (following ? unfollowTopic(topic.id) : followTopic(topic.id)))}
            >
              {t(following ? "board.unfollow" : "board.follow")}
            </button>
          </div>
        )}
        {zone.rights.moderate && (
          <div className="board-actions board-mod">
            <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => setTopic(topic.id, { pinned: !topic.pinned }))}>
              {t(topic.pinned ? "board.unpin" : "board.pin")}
            </button>
            <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => setTopic(topic.id, { locked: !topic.locked }))}>
              {t(topic.locked ? "board.unlock" : "board.lock")}
            </button>
            <button type="button" className="danger" disabled={act.isPending} onClick={() => void removeTopic()}>
              {t("board.deleteTopic")}
            </button>
          </div>
        )}
      </header>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <Pages at={at} pages={pages} onGo={goTo} />
      <ol className="board-posts">
        {posts.map((post) => (
          <PostItem key={post.id} post={post} zone={zone} mayReply={mayReply} busy={act.isPending} onQuote={quote} onReply={toReply} act={act.mutate} />
        ))}
      </ol>
      <Pages at={at} pages={pages} onGo={goTo} />
      <ReplyFoot zone={zone} locked={topic.locked} mayReply={mayReply}>
        <div ref={replyBox} className="board-reply">
          <h2>{t("board.yourReply")}</h2>
          <PostEditor
            key={replyKey}
            pictures={zone.pictures}
            busy={sendReply.isPending}
            insert={insert}
            label={t("board.yourReply")}
            follow={following ? undefined : { checked: followReply, onChange: setFollowReply }}
            onSubmit={(text, picture) => sendReply.mutate({ text, picture, follow: !following && followReply })}
          />
          {sendReply.isError && (
            <p className="notice error" role="alert">
              {sayError(sendReply.error)}
            </p>
          )}
        </div>
      </ReplyFoot>
    </main>
  );
}

/** A reply, its picture sent with `attachPicture` once the post is made. A picture refused leaves the reply made:
 * `onDone` is called either way, with the refusal. */
function useReply(topicId: string, onDone: (pictureError: string | null) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ text, picture, follow }: { text: string; picture: File | null; follow: boolean }) => {
      const made = await reply(topicId, text, follow);
      if (!picture) return null;
      return attachPicture(made.post.id, picture).then(
        () => null,
        (refused: unknown) => sayError(refused),
      );
    },
    onSuccess: (pictureError) => onDone(pictureError),
    onSettled: () => void client.invalidateQueries({ queryKey: boardKeys.all }),
  });
}

/** The foot of the topic: the reply box for who may reply, else why there is none (for a visitor, Log in to post
 * where accounts write, as on the zone's page). */
function ReplyFoot({ zone, locked, mayReply, children }: { zone: Zone; locked: boolean; mayReply: boolean; children: React.ReactNode }) {
  const t = useT();
  const { signedIn } = useReader();
  if (mayReply) return <>{children}</>;
  if (!signedIn && zone.write === "accounts")
    return (
      <p className="board-foot-note">
        <a className="button-like" href="/login">
          {t("board.logInToPost")}
        </a>
      </p>
    );
  if (locked && zone.rights.write)
    return (
      <p className="board-foot-note" data-testid="board-locked">
        <Lock size={14} aria-hidden="true" /> {t("board.lockedNote")}
      </p>
    );
  return null;
}

function Pages({ at, pages, onGo }: { at: number; pages: number; onGo: (page: number) => void }) {
  const t = useT();
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label={t("board.pages")}>
      <button type="button" disabled={at <= 1} onClick={() => onGo(at - 1)}>
        {t("pager.previous")}
      </button>
      <span className="pager-range">{t("board.pageOf", { page: String(at), pages: String(pages) })}</span>
      <button type="button" disabled={at >= pages} onClick={() => onGo(at + 1)}>
        {t("pager.next")}
      </button>
    </nav>
  );
}

/** The author's face: their uploaded picture (served by the board), their emblem, or for no account an initial. */
function Face({ post, name }: { post: Post; name: string }) {
  const author: Author = post.author;
  if (author.account_id === null || !author.avatar)
    return <Avatar profile={null} size={36} name={author.account_id === null ? name : undefined} />;
  const profile = { account_id: author.account_id, display_name: name, pronouns: "", avatar: author.avatar, colour: author.colour ?? "teal" };
  const src = "picture" in author.avatar ? `${postAvatarUrl(post.id)}?v=${encodeURIComponent(author.avatar.picture)}` : undefined;
  return <Avatar profile={profile} size={36} src={src} />;
}

function PostItem({
  post,
  zone,
  mayReply,
  busy,
  onQuote,
  onReply,
  act,
}: {
  post: Post;
  zone: Zone;
  mayReply: boolean;
  busy: boolean;
  onQuote: (post: Post) => void;
  onReply: () => void;
  act: (run: () => Promise<unknown>) => void;
}) {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const client = useQueryClient();
  const { signedIn } = useReader();
  const [editing, setEditing] = useState(false);
  const name = authorName(t, post.author);
  const moderate = zone.rights.moderate;
  const edit = useMutation({
    mutationFn: async ({ text, picture }: { text: string; picture: File | null }) => {
      await editPost(post.id, text);
      if (picture) await attachPicture(post.id, picture);
    },
    onSuccess: () => setEditing(false),
    onSettled: () => void client.invalidateQueries({ queryKey: boardKeys.all }),
  });
  const remove = async () => {
    const sure = await confirm({ title: t("board.deletePostConfirm"), confirm: t("board.delete"), danger: true });
    if (sure) act(() => deletePost(post.id));
  };

  return (
    <li id={`post-${post.id}`} className="board-post" data-testid="board-post">
      <header className="board-post-head">
        <Face post={post} name={name} />
        <div className="board-post-who">
          <strong>{name}</strong>
          {post.author.badges.map((badge) => (
            <span key={badge} className="board-badge">
              {BADGES[badge] ? t(BADGES[badge]) : badge}
            </span>
          ))}
          <span className="board-meta">
            <time dateTime={post.created_at}>{postTime(post.created_at, language)}</time>
            {post.edited_at && !post.removed && (
              <span className="board-edited" title={postTime(post.edited_at, language)}>
                {t("board.edited")}
              </span>
            )}
          </span>
        </div>
      </header>
      {post.removed ? (
        <p className="board-removed">{t(post.removed === "author" ? "board.removedByAuthor" : "board.removedByModerator")}</p>
      ) : editing ? (
        <>
          <PostEditor
            initial={post.text}
            pictures={zone.pictures}
            busy={edit.isPending}
            submitLabel={t("board.save")}
            label={t("board.editPost")}
            onCancel={() => setEditing(false)}
            onSubmit={(text, picture) => edit.mutate({ text, picture })}
          />
          {edit.isError && (
            <p className="notice error" role="alert">
              {sayError(edit.error)}
            </p>
          )}
        </>
      ) : (
        <>
          <div className="board-text" dangerouslySetInnerHTML={{ __html: renderPost(post.text) }} />
          {post.picture && (
            <Lightbox
              className="image-zoom board-picture"
              label={t("board.enlargePicture", { name })}
              title={t("board.pictureBy", { name })}
              big={<img className="lightbox-image" src={postPictureUrl(post.id)} alt={t("board.pictureBy", { name })} />}
            >
              <img src={postPictureUrl(post.id)} alt="" width={post.picture.width} height={post.picture.height} loading="lazy" />
            </Lightbox>
          )}
          <div className="board-actions board-post-actions">
            {mayReply && (
              <>
                <button type="button" onClick={() => onQuote(post)}>
                  {t("board.quote")}
                </button>
                <button type="button" onClick={onReply}>
                  {t("board.reply")}
                </button>
              </>
            )}
            {/* Editing needs the write right too (the server's `edit_post`); deleting one's own post doesn't. */}
            {post.mine && signedIn && zone.rights.write && (
              <button type="button" disabled={busy} onClick={() => setEditing(true)}>
                {t("board.edit")}
              </button>
            )}
            {((post.mine && signedIn) || moderate) && (
              <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
                {t("board.delete")}
              </button>
            )}
            {post.picture && ((post.mine && signedIn) || moderate) && (
              <button type="button" disabled={busy} onClick={() => act(() => takeDownPicture(post.id))}>
                {t("board.takePictureDown")}
              </button>
            )}
          </div>
        </>
      )}
    </li>
  );
}
