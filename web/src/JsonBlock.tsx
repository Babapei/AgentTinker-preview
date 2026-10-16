export default function JsonBlock({ value, empty }: { value: unknown; empty: string }) {
  return value === null || value === undefined ? (
    <p className="empty-inline">{empty}</p>
  ) : (
    <pre className="json-block" tabIndex={0}>
      <code>{JSON.stringify(value, null, 2)}</code>
    </pre>
  );
}
