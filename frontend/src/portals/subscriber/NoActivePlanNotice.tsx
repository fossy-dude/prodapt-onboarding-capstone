/** Shown on the dashboard for a subscriber with no active plan subscription yet. */
function NoActivePlanNotice() {
  return (
    <div
      role="status"
      className="rounded-xl bg-amber-50 border border-amber-200 p-6"
    >
      <p className="text-sm text-amber-800">
        Dashboard will be activated once you subscribe to a plan. Please add a
        payment method, and visit the &quot;Discover plans&quot; link on the
        side panel to subscribe to a plan.
      </p>
    </div>
  );
}

export { NoActivePlanNotice };
