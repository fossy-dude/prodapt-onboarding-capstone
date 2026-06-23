import { useState, useEffect, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  type BadgeVariant,
  Button,
  Card,
  CardSection,
} from "../../components/ui";
import { useProfile, useUpdateProfile } from "../../hooks/useProfile";
import {
  toApiError,
  type ProfileData,
  type ProfileUpdatePayload,
} from "../../lib/api";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const KYC_RESUBMIT_ROUTE = "/subscriber/profile/kyc";
// Generic rejection reason — no structured per-subscriber reason is stored on
// identity_kyc_records, so a fixed re-submit prompt is shown (user decision).
const KYC_REJECT_REASON =
  "Your KYC documents were not approved. Please re-submit them to verify your account.";

interface EditFormState {
  email: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  pin_code: string;
}

/** Map an API KYC status to the Badge variant + display label (AC #2). */
function kycBadge(status: string): { variant: BadgeVariant; label: string } {
  switch (status) {
    case "verified":
      return { variant: "verified", label: "Verified" };
    case "pending":
      return { variant: "pending", label: "Pending" };
    case "rejected":
      return { variant: "rejected", label: "Rejected" };
    default:
      return { variant: "neutral", label: status || "Unknown" };
  }
}

/** Render the KYC badge; on Rejected show the reason + a re-submit CTA (AC #2, #5). */
function KycStatus({ status }: { readonly status: string }) {
  const { variant, label } = kycBadge(status);
  if (status !== "rejected") {
    return <Badge variant={variant}>{label}</Badge>;
  }
  return (
    <div className="space-y-2">
      <Badge variant={variant}>{label}</Badge>
      <div
        role="alert"
        className="rounded-md border border-danger-200 bg-danger-50 p-3"
      >
        <p className="text-sm text-danger-700">{KYC_REJECT_REASON}</p>
        <Link
          to={KYC_RESUBMIT_ROUTE}
          className="mt-2 inline-block text-sm font-medium text-brand-700 underline"
        >
          Re-submit KYC documents
        </Link>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string | null;
}) {
  return (
    <div className="mb-2">
      <dt className="text-xs font-medium uppercase tracking-wide text-neutral-500">
        {label}
      </dt>
      <dd className="text-sm text-neutral-900">
        {value && value.trim() ? value : "Not set yet"}
      </dd>
    </div>
  );
}

interface FieldProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly type?: string;
}

function Field({ label, value, onChange, type = "text" }: FieldProps) {
  const fieldId = `profile-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="mb-3">
      <label
        className="mb-1 block text-sm font-medium text-neutral-800"
        htmlFor={fieldId}
      >
        {label}
      </label>
      <input
        id={fieldId}
        className="w-full rounded-md border border-neutral-200 px-3 py-2 text-base"
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/** Edit form for email + address; PATCH then invalidate the profile query (AC #3, #4). */
function EditProfileForm({ initial }: { readonly initial: ProfileData }) {
  const mutation = useUpdateProfile();
  const [form, setForm] = useState<EditFormState>(() => ({
    email: initial.email ?? "",
    address_line1: initial.address.line1 ?? "",
    address_line2: initial.address.line2 ?? "",
    city: initial.address.city ?? "",
    state: initial.address.state ?? "",
    pin_code: initial.address.pin_code ?? "",
  }));
  const [error, setError] = useState<string>("");
  const [saved, setSaved] = useState<boolean>(false);

  useEffect(() => {
    setForm({
      email: initial.email ?? "",
      address_line1: initial.address.line1 ?? "",
      address_line2: initial.address.line2 ?? "",
      city: initial.address.city ?? "",
      state: initial.address.state ?? "",
      pin_code: initial.address.pin_code ?? "",
    });
    setError("");
    setSaved(false);
  }, [initial]);

  const setField = (key: keyof EditFormState, value: string): void => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError("");
    setSaved(false);
  };

  const handleSubmit = (event: FormEvent): void => {
    event.preventDefault();
    if (mutation.isPending) return;
    if (form.email && !EMAIL_RE.test(form.email)) {
      setError("Please enter a valid email address.");
      return;
    }
    const payload: ProfileUpdatePayload = { ...form };
    mutation.mutate(payload, {
      onSuccess: () => setSaved(true),
      onError: (err: unknown) =>
        setError(
          toApiError(err)?.message ??
            "Could not save changes. Please try again.",
        ),
    });
  };

  return (
    <Card>
      <form onSubmit={handleSubmit} noValidate>
        <CardSection title="Edit profile">
          <p className="mb-3 text-sm text-neutral-600">
            Update your email or address. Your name is managed during
            registration.
          </p>
          <Field
            label="Email"
            value={form.email}
            type="email"
            onChange={(v) => setField("email", v)}
          />
          <Field
            label="Address line 1"
            value={form.address_line1}
            onChange={(v) => setField("address_line1", v)}
          />
          <Field
            label="Address line 2"
            value={form.address_line2}
            onChange={(v) => setField("address_line2", v)}
          />
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="City"
              value={form.city}
              onChange={(v) => setField("city", v)}
            />
            <Field
              label="State"
              value={form.state}
              onChange={(v) => setField("state", v)}
            />
          </div>
          <Field
            label="PIN code"
            value={form.pin_code}
            onChange={(v) => setField("pin_code", v)}
          />
          {error && (
            <p role="alert" className="mb-3 text-sm text-danger-600">
              {error}
            </p>
          )}
          {saved && (
            <p role="status" className="mb-3 text-sm text-success-700">
              Profile updated.
            </p>
          )}
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save changes"}
          </Button>
        </CardSection>
      </form>
    </Card>
  );
}

/** Read-only profile summary (AC #1, #2, #5). */
function ProfileSummary({ profile }: { readonly profile: ProfileData }) {
  return (
    <Card>
      <CardSection title="Personal details">
        <dl>
          <DetailRow label="Name" value={profile.name} />
          <DetailRow label="Email" value={profile.email} />
          <div className="mt-3">
            <dt className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">
              KYC status
            </dt>
            <dd>
              <KycStatus status={profile.kyc_status} />
            </dd>
          </div>
        </dl>
      </CardSection>
      <CardSection title="Saved address">
        <dl>
          <DetailRow label="Address line 1" value={profile.address.line1} />
          <DetailRow label="Address line 2" value={profile.address.line2} />
          <DetailRow label="City" value={profile.address.city} />
          <DetailRow label="State" value={profile.address.state} />
          <DetailRow label="PIN code" value={profile.address.pin_code} />
        </dl>
      </CardSection>
    </Card>
  );
}

/**
 * Subscriber profile page (Story 1.9). Route: /subscriber/profile (behind
 * /subscriber/* RoleGuard). Renders the decrypted profile + KYC Badge and an
 * edit form that PATCHes email/address via TanStack Query.
 */
export function Profile() {
  const { data, isLoading, isError } = useProfile();
  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold text-neutral-900">Your profile</h1>
      {isLoading && (
        <p role="status" className="text-sm text-neutral-500">
          Loading your profile…
        </p>
      )}
      {isError && (
        <p role="alert" className="text-sm text-danger-600">
          Unable to load your profile. Please refresh or contact support.
        </p>
      )}
      {data && (
        <div className="space-y-6">
          <ProfileSummary profile={data} />
          <EditProfileForm initial={data} />
        </div>
      )}
    </main>
  );
}
