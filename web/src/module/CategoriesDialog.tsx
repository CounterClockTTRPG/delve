import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  createModuleCategory,
  deleteModuleCategory,
  listModuleCategories,
  queryKeys,
  updateModuleCategory,
  type ModuleCategory,
  type ModuleSummary,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";

/**
 * The organisers' categories of modules (DEL-114): add one, rename one (on Enter or leaving its field), move one up
 * or down, or delete one, whose modules then have none (after a confirmation that says how many). `modules` are the
 * module list, for those counts.
 */
export default function CategoriesDialog({ modules, onClose }: { modules: ModuleSummary[]; onClose: () => void }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const categories = useQuery({ queryKey: queryKeys.moduleCategories, queryFn: listModuleCategories });
  const [name, setName] = useState("");
  const refresh = () => {
    client.invalidateQueries({ queryKey: queryKeys.moduleCategories });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  const add = useMutation({ mutationFn: createModuleCategory, onSuccess: () => (setName(""), refresh()) });
  const change = useMutation({
    mutationFn: ({ id, ...rest }: { id: string; name?: string; position?: number }) => updateModuleCategory(id, rest),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: deleteModuleCategory, onSuccess: refresh });
  const failed = add.error ?? change.error ?? remove.error;
  const listed = categories.data ?? [];

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) add.mutate(name.trim());
  }

  async function drop(category: ModuleCategory) {
    const count = modules.filter((m) => m.category?.id === category.id).length;
    const ok = await confirm({
      title: t("moduleCategories.deleteConfirm", { name: category.name }),
      body: count === 1 ? t("moduleCategories.deleteMovesOne") : t("moduleCategories.deleteMoves", { count: String(count) }),
      confirm: t("dialog.delete"),
      danger: true,
    });
    if (ok) remove.mutate(category.id);
  }

  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog categories-dialog">
          <Dialog.Title className="dialog-title">{t("moduleCategories.title")}</Dialog.Title>
          <Dialog.Description className="dialog-body">{t("moduleCategories.lede")}</Dialog.Description>
          {failed && (
            <p role="alert" className="notice error">
              {failed.message}
            </p>
          )}
          {listed.length === 0 ? (
            <p className="placeholder">{t("moduleCategories.empty")}</p>
          ) : (
            <ol className="category-list">
              {listed.map((category, index) => (
                <CategoryRow
                  key={`${category.id}-${category.name}`}
                  category={category}
                  first={index === 0}
                  last={index === listed.length - 1}
                  busy={change.isPending || remove.isPending}
                  onRename={(next, refused) =>
                    next !== category.name && change.mutate({ id: category.id, name: next }, { onError: refused })
                  }
                  onMove={(by) => change.mutate({ id: category.id, position: index + by })}
                  onDelete={() => void drop(category)}
                />
              ))}
            </ol>
          )}
          <form className="category-add" onSubmit={submit}>
            <label htmlFor="category-new" className="visually-hidden">
              {t("moduleCategories.newLabel")}
            </label>
            <input
              id="category-new"
              value={name}
              maxLength={60}
              placeholder={t("moduleCategories.newPlaceholder")}
              onChange={(e) => setName(e.target.value)}
            />
            <button type="submit" disabled={!name.trim() || add.isPending}>
              {t("moduleCategories.add")}
            </button>
          </form>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("moduleCategories.done")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CategoryRow({
  category,
  first,
  last,
  busy,
  onRename,
  onMove,
  onDelete,
}: {
  category: ModuleCategory;
  first: boolean;
  last: boolean;
  busy: boolean;
  /** `refused` puts the name back when the server refuses it (DEL-174). */
  onRename: (name: string, refused: () => void) => void;
  onMove: (by: -1 | 1) => void;
  onDelete: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(category.name);
  const commit = () => (name.trim() ? onRename(name.trim(), () => setName(category.name)) : setName(category.name));
  return (
    <li className="category-row">
      <input
        aria-label={t("moduleCategories.nameOf", { name: category.name })}
        value={name}
        maxLength={60}
        onChange={(e) => setName(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
      />
      <button type="button" aria-label={t("moduleCategories.up", { name: category.name })} disabled={first || busy} onClick={() => onMove(-1)}>
        ↑
      </button>
      <button type="button" aria-label={t("moduleCategories.down", { name: category.name })} disabled={last || busy} onClick={() => onMove(1)}>
        ↓
      </button>
      <button type="button" className="danger" disabled={busy} onClick={onDelete}>
        {t("dialog.delete")}
      </button>
    </li>
  );
}
