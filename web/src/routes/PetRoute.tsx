import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { PetSummary } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./PetRoute.module.css";

export function PetRoute() {
  const { t } = useAppI18n();
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
  });

  const pet = petQuery.data;
  const progress = pet ? Math.round((pet.exp / pet.expToNext) * 100) : 0;

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.avatarPanel}>
          <div className={styles.avatarOrb}>{pet?.name?.[0] ?? "P"}</div>
          <p className={styles.avatarMeta}>
            {pet?.avatarPreset ?? "lobster"} {t("preset")}
          </p>
        </div>
        <div>
          <p className={styles.eyebrow}>{t("petSpace")}</p>
          <h1 className={styles.title}>{pet?.name ?? t("loadingPetState")}</h1>
          <p className={styles.statusLine}>{pet?.statusLine ?? t("readingCompanionState")}</p>
        </div>
      </section>

      <section className={styles.metricGrid}>
        <article className={styles.metricCard}>
          <span>{t("level")}</span>
          <strong>{pet?.level ?? 0}</strong>
        </article>
        <article className={styles.metricCard}>
          <span>{t("tasks")}</span>
          <strong>{pet?.totalTasks ?? 0}</strong>
        </article>
        <article className={styles.metricCard}>
          <span>{t("friends")}</span>
          <strong>{pet?.friendCount ?? 0}</strong>
        </article>
        <article className={styles.metricCard}>
          <span>{t("tokens")}</span>
          <strong>{pet?.totalTokens ?? 0}</strong>
        </article>
      </section>

      <section className={styles.statusGrid}>
        <article className={styles.card}>
          <p className={styles.cardTitle}>{t("vitals")}</p>
          <div className={styles.statList}>
            <span>{t("mood")} {pet?.mood ?? 0}</span>
            <span>{t("hunger")} {pet?.hunger ?? 0}</span>
            <span>{t("energy")} {pet?.energy ?? 0}</span>
            <span>{t("health")} {pet?.health ?? 0}</span>
            <span>{t("love")} {pet?.love ?? 0}</span>
          </div>
        </article>

        <article className={styles.card}>
          <p className={styles.cardTitle}>{t("progress")}</p>
          <div className={styles.progressTrack}>
            <div className={styles.progressFill} style={{ width: `${progress}%` }} />
          </div>
          <p className={styles.supportText}>
            {pet?.exp ?? 0} / {pet?.expToNext ?? 0} {t("exp")}
          </p>
        </article>

        <article className={styles.card}>
          <p className={styles.cardTitle}>{t("state")}</p>
          <div className={styles.statList}>
            <span>{t("heart")} {pet?.heartActive ? t("heartActive") : t("heartIdle")}</span>
            <span>{t("dream")} {pet?.inDream ? t("dreamSleeping") : t("dreamAwake")}</span>
            <span>{t("dailyTokens")} {pet?.dailyTokens ?? 0}</span>
          </div>
        </article>
      </section>

      <section className={styles.card}>
        <p className={styles.cardTitle}>{t("achievements")}</p>
        <div className={styles.badgeRow}>
          {(pet?.achievements ?? []).length > 0 ? (
            pet?.achievements.map((achievement) => (
              <span key={achievement} className={styles.badge}>
                {achievement}
              </span>
            ))
          ) : (
            <span className={styles.supportText}>{t("noAchievements")}</span>
          )}
        </div>
      </section>
    </div>
  );
}
