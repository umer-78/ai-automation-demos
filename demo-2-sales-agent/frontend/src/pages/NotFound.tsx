import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="py-20 text-center">
      <h1 className="display text-[40px]">Nothing on the radar here</h1>
      <p className="mt-3 text-ink-2">This page does not exist.</p>
      <Link to="/" className="link mt-6 inline-block font-semibold">
        Back to the overview
      </Link>
    </div>
  );
}
