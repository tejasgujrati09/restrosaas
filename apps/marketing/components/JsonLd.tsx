// Renders a JSON-LD <script> tag. Server component; data is always ours, never user input, so a
// plain JSON.stringify is safe here.
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}
