import { NavLink } from "react-router-dom";

import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceTabs.module.css";

type SupervisedWorkspaceView = "live" | "runs" | "library" | "review";

type SupervisedWorkspaceTabsProps = {
  activeView: SupervisedWorkspaceView;
};

const VIEWS: Array<{ key: SupervisedWorkspaceView; href: string; end?: boolean }> = [
  { key: "live", href: "/supervised-evolution", end: true },
  { key: "runs", href: "/supervised-evolution/runs", end: true },
  { key: "library", href: "/supervised-evolution/library", end: true },
  { key: "review", href: "/supervised-evolution/review", end: true },
];

export function SupervisedWorkspaceTabs({ activeView }: SupervisedWorkspaceTabsProps) {
  const { t, viewLabel } = useAppI18n();

  return (
    <div className={styles.segmented} role="tablist" aria-label={t("navSupervisedEvolution")}>
      {VIEWS.map((view) => {
        const label = view.key === "review" ? t("reviewWorkspace") : viewLabel(view.key);
        return (
          <NavLink
            key={view.key}
            to={view.href}
            end={view.end}
            className={({ isActive }) =>
              isActive || activeView === view.key
                ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                : styles.segmentButton
            }
          >
            {label}
          </NavLink>
        );
      })}
    </div>
  );
}
