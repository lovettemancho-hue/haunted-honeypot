/** Marks a replay entry whose response was invented by the LLM. */
export function StitchedTag() {
  return (
    <span className="stitched">
      <span className="tag-stitched">Stitched</span>{" "}
      <span className="stitched-note">the AI invented this response</span>
    </span>
  );
}
