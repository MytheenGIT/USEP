import { HTMLAttributes, ReactNode } from "react";

interface Props extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title?: ReactNode;
  actions?: ReactNode;
  as?: "section" | "div" | "article";
}

export function Card({ title, actions, as: Tag = "section", className = "", children, ...rest }: Props) {
  return (
    <Tag {...rest} className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 className="card-title">{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </Tag>
  );
}
