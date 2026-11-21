import { Link } from "react-router-dom";
import { Card, Section, btn } from "../world/Section";

export default function NotFound() {
  return (
    <Section shot="home">
      <Card>
        <h1 className="text-[32px] font-semibold leading-tight tracking-[-0.03em]">Nothing on the radar here</h1>
        <p className="mt-2 text-[15px] text-ink-2">This page does not exist. The radar behind this card is where every researched company sits.</p>
        <Link to="/" className={`${btn.primary} mt-5`}>
          Back to the overview
        </Link>
      </Card>
    </Section>
  );
}
