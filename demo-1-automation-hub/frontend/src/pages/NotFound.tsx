import { Link } from "react-router-dom";
import { Card, CardTitle, Section, btn } from "../world/Section";

export default function NotFound() {
  return (
    <Section shot="home">
      <Card>
        <CardTitle>This page does not exist</CardTitle>
        <p className="text-[15px] text-[#3f444c]">The address may be old or mistyped. Everything in the hub is one click from the overview.</p>
        <Link to="/" className={`${btn.primary} mt-5`}>
          Back to the overview
        </Link>
      </Card>
    </Section>
  );
}
