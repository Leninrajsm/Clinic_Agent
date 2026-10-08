export function PolicyDiff({ diff }: { diff: string }) {
  if (!diff.trim()) return <div className="text-sm text-slate-500">No differences.</div>;
  return (
    <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed">
      {diff.split("\n").map((line, i) => {
        let cls = "text-slate-300";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "text-emerald-300 bg-emerald-950/60";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "text-rose-300 bg-rose-950/60";
        else if (line.startsWith("@@")) cls = "text-sky-300";
        return (
          <div key={i} className={`whitespace-pre-wrap ${cls}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
