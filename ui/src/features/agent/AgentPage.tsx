import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, navigate, paths } from "../../app/router";
import { api } from "../../shared/api/client";
import { GraphDto, GraphNodeDto } from "../../shared/api/types";
import { useAsync } from "../../shared/hooks/useAsync";
import { Badge, Button, EmptyState, Icon, Spinner } from "../../shared/ui";
import { useSession } from "../auth/AuthContext";
import { useConfigurationList } from "../configurations/ConfigurationsContext";
import { conceptColor } from "../graph/colors";
import { Answer, answerQuestion, SUGGESTED_QUESTIONS } from "./answer";

interface Turn {
  id: number;
  question: string;
  answer?: Answer;
}

const THINKING_MS = 700;

function Chip({ node }: { node: GraphNodeDto }) {
  return <span className="cite" title={`${node.concept}${node.source_system ? ` from ${node.source_system}` : ""}`}><span className="dot" style={{ background: conceptColor(node.concept) }} aria-hidden="true" />{node.name}</span>;
}

/** The chat that comes after the knowledge graph. A mock-up: it answers from the graph on screen, not from a language model. */
export function AgentPage({ id }: { id?: string }) {
  const { session, guard } = useSession();
  const { items } = useConfigurationList();
  const ready = useMemo(() => (items ?? []).filter((c) => c.status === "ready"), [items]);
  const chosen = id ?? ready[0]?.id;
  const graph = useAsync<GraphDto | null>(() => (chosen ? guard(api.getGraph(session.token, chosen)) : Promise.resolve(null)), [chosen, session.token]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const counter = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => { setTurns([]); }, [chosen]);
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [turns]);

  if (!items) return <Spinner label="Loading" />;
  if (ready.length === 0) {
    return (
      <>
        <div className="page-head"><div><h1>Ask the agent</h1><p className="muted">Ask questions about a knowledge graph in plain English.</p></div></div>
        <EmptyState title="No knowledge graph yet" action={<Button variant="primary" onClick={() => navigate(paths.newConfiguration())}>Create a configuration</Button>}>
          The agent answers from a knowledge graph. Create a configuration and wait for it to finish processing.
        </EmptyState>
      </>
    );
  }

  const config = ready.find((c) => c.id === chosen);
  const ask = (question: string) => {
    const text = question.trim();
    if (!text || !graph.data) return;
    const turn: Turn = { id: ++counter.current, question: text };
    setTurns((t) => [...t, turn]);
    setDraft("");
    const g = graph.data;
    timers.current.push(window.setTimeout(() => setTurns((t) => t.map((x) => (x.id === turn.id ? { ...x, answer: answerQuestion(g, text) } : x))), THINKING_MS));
  };
  const submit = (e: FormEvent) => { e.preventDefault(); ask(draft); };

  return (
    <div className="agent">
      <div className="page-head">
        <div>
          <h1>Ask the agent</h1>
          <p className="muted">Questions are answered from the knowledge graph you pick. <Badge tone="warning" title="Answers come from the graph on screen with fixed question shapes">preview</Badge></p>
        </div>
        <div className="row-gap">
          <label className="agent-pick">
            <span className="sr-only">Knowledge graph</span>
            <select value={chosen} onChange={(e) => navigate(paths.agent(e.target.value))} aria-label="Knowledge graph">
              {ready.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          {config && <Link to={paths.graph(config.id)} className="btn btn-secondary"><Icon name="graph" size={16} /> View the graph</Link>}
        </div>
      </div>

      <div className="card chat">
        <div className="chat-log" aria-live="polite">
          {turns.length === 0 && (
            <div className="chat-empty">
              <span className="chat-empty-mark"><Icon name="chat" size={26} /></span>
              <h2>What would you like to know?</h2>
              <p className="muted">{graph.loading ? "Loading the graph…" : graph.data ? `${graph.data.nodes.length} nodes and ${graph.data.edges.length} relationships to ask about.` : "The graph could not be loaded."}</p>
              <div className="chat-suggestions">
                {SUGGESTED_QUESTIONS.map((q) => <button key={q} type="button" className="suggestion suggestion-lg" onClick={() => ask(q)} disabled={!graph.data}>{q}</button>)}
              </div>
            </div>
          )}
          {turns.map((t) => (
            <div key={t.id} className="turn">
              <div className="bubble bubble-user">{t.question}</div>
              {t.answer ? (
                <div className="bubble bubble-agent">
                  <p>{t.answer.text}</p>
                  {t.answer.citations.length > 0 && <div className="cites" aria-label="Based on">{t.answer.citations.map((n) => <Chip key={n.id} node={n} />)}</div>}
                </div>
              ) : (
                <div className="bubble bubble-agent bubble-thinking" aria-label="The agent is thinking"><span className="dots" aria-hidden="true"><i /><i /><i /></span></div>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>
        <form className="chat-input" onSubmit={submit}>
          <input aria-label="Your question" placeholder="Ask about requirements, changes, incidents, owners…" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={!graph.data} autoComplete="off" />
          <Button variant="primary" type="submit" disabled={!draft.trim() || !graph.data}><Icon name="send" size={16} /> Ask</Button>
        </form>
      </div>
    </div>
  );
}
