import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ResetSummary } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./ResetRoute.module.css";

export function ResetRoute() {
  const { lang, t } = useAppI18n();
  const resetQuery = useQuery({
    queryKey: queryKeys.resetSummary(),
    queryFn: () => fetchJson<ResetSummary>("/api/reset/summary"),
  });

  const summary = resetQuery.data;

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>{t("reset")}</p>
        <h1 className={styles.title}>{t("workspaceResetSurface")}</h1>
        <p className={styles.warning}>{summary?.warning ?? t("loadingResetInventory")}</p>
      </section>

      <section className={styles.presetGrid}>
        {(summary?.presets ?? []).map((preset) => (
          <article key={preset.id} className={styles.card}>
            <p className={styles.cardTitle}>{preset.label}</p>
            <p className={styles.cardText}>
              {t("categories")}: {preset.keys.join(", ")}
            </p>
          </article>
        ))}
      </section>

      <section className={styles.card}>
        <p className={styles.cardTitle}>{t("currentResetInventory")}</p>
        <div className={styles.inventoryGrid}>
          {(summary?.categories ?? []).map((category) => (
            <article key={category.id} className={styles.inventoryItem}>
              <div className={styles.inventoryTop}>
                <strong>{category.name}</strong>
                <span>{category.exists ? t("present") : t("missing")}</span>
              </div>
              <p className={styles.cardText}>{category.description}</p>
              <p className={styles.metaLine}>
                {lang === "zh"
                  ? `${category.size} · ${category.fileCount} ${t("filesCount")}`
                  : `${category.size} · ${category.fileCount} ${t("filesCount")}`}
              </p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
