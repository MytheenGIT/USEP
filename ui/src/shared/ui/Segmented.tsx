interface Option<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

interface Props<T extends string> {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}

/** A small either-or choice, drawn like the graph/table switch. A radio group underneath, so the arrow keys work. */
export function Segmented<T extends string>({ label, value, options, onChange }: Props<T>) {
  return (
    <div role="radiogroup" aria-label={label} className="segmented segmented-choice">
      {options.map((o) => (
        <button
          key={o.value} type="button" role="radio" aria-checked={value === o.value} disabled={o.disabled} title={o.title}
          className={value === o.value ? "seg active" : "seg"} onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
