import { Check, Circle, X } from 'lucide-react';
import { statusLabels } from './observations';
import type { Run, Span } from './protocol';

export default function Status({ status }: { status: Run['status'] | Span['status'] }) {
  return (
    <span className={`status status-${status}`}>
      {status === 'succeeded' ? (
        <Check size={12} />
      ) : status === 'failed' ? (
        <X size={12} />
      ) : (
        <Circle size={9} />
      )}
      {statusLabels[status]}
    </span>
  );
}
