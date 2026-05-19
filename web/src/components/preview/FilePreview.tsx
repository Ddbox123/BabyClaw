import { type ReactNode, useMemo } from "react";

import CodeMirror from "@uiw/react-codemirror";
import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { yaml } from "@codemirror/lang-yaml";

import { FileContent } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { classifyLogText, matchesSeverityFilter, type LogSeverityFilter } from "../../logs/logSeverity";
import styles from "./FilePreview.module.css";

type FilePreviewProps = {
  file: FileContent;
  changed: boolean;
  sourceLabel: string;
  headerActions?: ReactNode;
  highlightAsLog?: boolean;
  severityFilter?: LogSeverityFilter;
};

function getExtensions(language: string) {
  switch (language) {
    case "python":
      return [python(), EditorView.lineWrapping];
    case "json":
      return [json(), EditorView.lineWrapping];
    case "markdown":
      return [markdown(), EditorView.lineWrapping];
    case "yaml":
      return [yaml(), EditorView.lineWrapping];
    case "javascript":
    case "typescript":
    case "tsx":
      return [javascript({ typescript: true, jsx: language === "tsx" }), EditorView.lineWrapping];
    default:
      return [EditorView.lineWrapping];
  }
}

const logLineDecorations = EditorView.decorations.compute([], (state) => {
  const builder = new RangeSetBuilder<Decoration>();
  for (let lineNumber = 1; lineNumber <= state.doc.lines; lineNumber += 1) {
    const line = state.doc.line(lineNumber);
    const severity = classifyLogText(line.text);
    if (severity === "error") {
      builder.add(line.from, line.from, Decoration.line({ class: "cm-logLineError" }));
      continue;
    }
    if (severity === "warning") {
      builder.add(line.from, line.from, Decoration.line({ class: "cm-logLineWarning" }));
    }
  }
  return builder.finish();
});

const logHighlightTheme = EditorView.baseTheme({
  ".cm-logLineError": {
    backgroundColor: "rgba(187, 108, 93, 0.14)",
  },
  ".cm-logLineWarning": {
    backgroundColor: "rgba(215, 160, 84, 0.12)",
  },
});

export function FilePreview({
  file,
  changed,
  sourceLabel,
  headerActions,
  highlightAsLog = false,
  severityFilter = "all",
}: FilePreviewProps) {
  const { t } = useAppI18n();
  const extensions = getExtensions(file.language);
  const editorExtensions = highlightAsLog ? [...extensions, logLineDecorations, logHighlightTheme] : extensions;
  const displayContent = useMemo(() => {
    if (!highlightAsLog || severityFilter === "all") {
      return file.content;
    }
    const matchingLines = file.content
      .split(/\r?\n/)
      .filter((line) => matchesSeverityFilter(classifyLogText(line), severityFilter));
    return matchingLines.length > 0 ? matchingLines.join("\n") : t("logSeverityEmpty");
  }, [file.content, highlightAsLog, severityFilter, t]);

  return (
    <div className={styles.surface}>
      <div className={styles.header}>
        <div className={styles.headerCopy}>
          <p className={styles.eyebrow}>{t("readonlyPreview")}</p>
          <h2 className={styles.fileName}>{file.path.split("/").at(-1)}</h2>
          <p className={styles.filePath}>{file.path}</p>
        </div>
        <div className={styles.metaBlock}>
          {changed ? <span className={styles.changedPill}>{t("changed")}</span> : null}
          <span className={styles.sourcePill}>{sourceLabel}</span>
          {headerActions}
        </div>
      </div>

      <div className={styles.editorWrap}>
        <CodeMirror
          value={displayContent}
          editable={false}
          theme={oneDark}
          height="100%"
          extensions={editorExtensions}
          basicSetup={{
            foldGutter: false,
            dropCursor: false,
            allowMultipleSelections: false,
            indentOnInput: false,
          }}
        />
      </div>

      {file.truncated ? <p className={styles.footnote}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
