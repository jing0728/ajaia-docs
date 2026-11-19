import TurndownService from "turndown";

const turndown = new TurndownService({
  headingStyle: "atx", // "# Heading" rather than underlined headings
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
});
// Markdown has no underline; keep the text. Strikethrough uses the common ~~ syntax.
turndown.addRule("strike", { filter: ["s", "del"], replacement: (content) => `~~${content}~~` });

function safeFilename(title) {
  return title.replace(/[\\/:*?"<>|]+/g, "-").trim().slice(0, 100) || "document";
}

export function downloadMarkdown(title, html) {
  const markdown = `# ${title}\n\n${turndown.turndown(html)}\n`;
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safeFilename(title)}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

export function printAsPdf(title) {
  // The print stylesheet hides everything but the document; the browser's
  // print dialog offers "Save as PDF". The page title becomes the default file name.
  const previous = document.title;
  document.title = safeFilename(title);
  window.print();
  document.title = previous;
}
