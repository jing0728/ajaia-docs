import { useEffect, useReducer } from "react";

function setLink(editor) {
  if (editor.isActive("link")) return editor.chain().focus().unsetLink().run();
  const url = window.prompt("Link address (https://…)");
  if (!url) return;
  if (!/^(https?:\/\/|mailto:)/i.test(url.trim())) {
    window.alert("Links must start with http://, https:// or mailto:");
    return;
  }
  editor.chain().focus().extendMarkRange("link").setLink({ href: url.trim() }).run();
}

// Each button: label, tooltip, whether it is active, whether it is disabled, what it does.
const BUTTONS = [
  { label: "B", title: "Bold (Ctrl+B)", style: { fontWeight: 700 }, active: (e) => e.isActive("bold"), run: (e) => e.chain().focus().toggleBold().run() },
  { label: "I", title: "Italic (Ctrl+I)", style: { fontStyle: "italic" }, active: (e) => e.isActive("italic"), run: (e) => e.chain().focus().toggleItalic().run() },
  { label: "U", title: "Underline (Ctrl+U)", style: { textDecoration: "underline" }, active: (e) => e.isActive("underline"), run: (e) => e.chain().focus().toggleUnderline().run() },
  { label: "S", title: "Strikethrough", style: { textDecoration: "line-through" }, active: (e) => e.isActive("strike"), run: (e) => e.chain().focus().toggleStrike().run() },
  "sep",
  { label: "H1", title: "Heading 1", active: (e) => e.isActive("heading", { level: 1 }), run: (e) => e.chain().focus().toggleHeading({ level: 1 }).run() },
  { label: "H2", title: "Heading 2", active: (e) => e.isActive("heading", { level: 2 }), run: (e) => e.chain().focus().toggleHeading({ level: 2 }).run() },
  { label: "H3", title: "Heading 3", active: (e) => e.isActive("heading", { level: 3 }), run: (e) => e.chain().focus().toggleHeading({ level: 3 }).run() },
  "sep",
  { label: "• List", title: "Bulleted list", active: (e) => e.isActive("bulletList"), run: (e) => e.chain().focus().toggleBulletList().run() },
  { label: "1. List", title: "Numbered list", active: (e) => e.isActive("orderedList"), run: (e) => e.chain().focus().toggleOrderedList().run() },
  { label: "❝", title: "Quote", active: (e) => e.isActive("blockquote"), run: (e) => e.chain().focus().toggleBlockquote().run() },
  { label: "Link", title: "Add or remove a link", active: (e) => e.isActive("link"), run: setLink },
  "sep",
  { label: "↶", title: "Undo (Ctrl+Z)", active: () => false, disabled: (e) => !e.can().undo(), run: (e) => e.chain().focus().undo().run() },
  { label: "↷", title: "Redo (Ctrl+Shift+Z)", active: () => false, disabled: (e) => !e.can().redo(), run: (e) => e.chain().focus().redo().run() },
];

export default function Toolbar({ editor }) {
  // Re-render when the selection or content changes so active states stay correct.
  const [, rerender] = useReducer((n) => n + 1, 0);
  useEffect(() => {
    if (!editor) return;
    editor.on("transaction", rerender);
    return () => editor.off("transaction", rerender);
  }, [editor]);

  if (!editor) return null;

  return (
    <div className="toolbar" role="toolbar" aria-label="Formatting">
      {BUTTONS.map((b, i) =>
        b === "sep" ? (
          <span key={i} className="sep" />
        ) : (
          <button
            key={b.title}
            type="button"
            title={b.title}
            aria-label={b.title}
            aria-pressed={b.active(editor)}
            disabled={b.disabled?.(editor)}
            className={b.active(editor) ? "tool active" : "tool"}
            style={b.style}
            onMouseDown={(e) => e.preventDefault()} // keep the editor's selection
            onClick={() => b.run(editor)}
          >
            {b.label}
          </button>
        )
      )}
    </div>
  );
}
