// Small avatar stack showing who else has this document open right now.

const COLORS = ["#2f5bea", "#1d7a45", "#b4462b", "#7a3fb5", "#a26a00"];

function initials(name) {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function Presence({ others }) {
  if (others.length === 0) return null;
  const names = others.map((o) => o.name.split(" ")[0]).join(", ");
  return (
    <div className="presence" title={`Also here: ${others.map((o) => o.name).join(", ")}`}>
      {others.map((o) => (
        <span key={o.id} className="avatar" style={{ background: COLORS[o.id % COLORS.length] }} aria-hidden="true">
          {initials(o.name)}
        </span>
      ))}
      <span className="presence-text">{names} {others.length === 1 ? "is" : "are"} here</span>
    </div>
  );
}
