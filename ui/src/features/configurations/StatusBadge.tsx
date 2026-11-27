import { ConfigStatus, SourceState } from "../../shared/api/types";
import { Badge, Tone } from "../../shared/ui";

const CONFIG_TONE: Record<ConfigStatus, Tone> = { submitted: "info", processing: "warning", ready: "success", failed: "danger" };
const SOURCE_TONE: Record<SourceState, Tone> = { pending: "info", success: "success", failed: "danger", skipped: "neutral" };

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const StatusBadge = ({ status }: { status: ConfigStatus }) => <Badge tone={CONFIG_TONE[status]}>{cap(status)}</Badge>;
export const SourceBadge = ({ state }: { state: SourceState }) => <Badge tone={SOURCE_TONE[state]}>{cap(state)}</Badge>;
