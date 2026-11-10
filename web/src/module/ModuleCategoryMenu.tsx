import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listModuleCategories, queryKeys, setModuleCategory, type ModuleSummary } from "../api";
import { useT } from "../i18n";

/** A module's category on its page (DEL-114): the list, and "No category"; nothing while there are no categories. */
export default function ModuleCategoryMenu({ module }: { module: ModuleSummary }) {
  const t = useT();
  const client = useQueryClient();
  const categories = useQuery({ queryKey: queryKeys.moduleCategories, queryFn: listModuleCategories }).data ?? [];
  const put = useMutation({
    mutationFn: (categoryId: string | null) => setModuleCategory(module.id, categoryId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.module(module.id), exact: true });
      client.invalidateQueries({ queryKey: queryKeys.modules });
    },
  });
  if (categories.length === 0) return null;
  return (
    <div className="field module-category">
      <label htmlFor="module-category">{t("moduleCategories.label")}</label>
      <select
        id="module-category"
        value={module.category?.id ?? ""}
        disabled={put.isPending}
        onChange={(e) => put.mutate(e.target.value || null)}
      >
        <option value="">{t("moduleCategories.none")}</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
      {put.error && (
        <p role="alert" className="notice error">
          {put.error.message}
        </p>
      )}
    </div>
  );
}
