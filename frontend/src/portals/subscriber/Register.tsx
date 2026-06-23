import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import { Badge, Button, Card, CardSection } from "../../components/ui";
import { ERROR_CODES, registerSubscriber, toApiError } from "../../lib/api";
import type { RegisterPayload } from "../../types/subscriber";

const ID_PROOF_TYPES = ["Aadhaar", "PAN", "Passport", "Voter ID"] as const;
const MSISDN_RE = /^\d{10,15}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface FormState {
  full_name: string;
  email: string;
  msisdn: string;
  alternate_mobile: string;
  date_of_birth: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  pin_code: string;
  id_proof_type: (typeof ID_PROOF_TYPES)[number];
  id_proof_number: string;
  consent: boolean;
}

const EMPTY_FORM: FormState = {
  full_name: "",
  email: "",
  msisdn: "",
  alternate_mobile: "",
  date_of_birth: "",
  address_line1: "",
  address_line2: "",
  city: "",
  state: "",
  pin_code: "",
  id_proof_type: "Aadhaar",
  id_proof_number: "",
  consent: false,
};

type Step = 1 | 2 | 3;

/**
 * Multi-step subscriber registration form (UX brief §5).
 *
 * Step 1 — personal details + alternate mobile (pre-activation OTP target, PRD A-6).
 * Step 2 — TRAI CAF fields; submit creates the registration.
 * Step 3 — Registration ID display + OTP entry (OTP verification lands in Story 1.8).
 *
 * A 409 DUPLICATE_MSISDN from the API surfaces as an inline error on the MSISDN
 * field in Step 1 (AC #8).
 */
function Register() {
  const [step, setStep] = useState<Step>(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [registrationId, setRegistrationId] = useState<string>("");
  const [otp, setOtp] = useState<string>("");
  const [stepError, setStepError] = useState<string>("");

  const mutation = useMutation({
    mutationFn: registerSubscriber,
    onSuccess: (envelope) => {
      setRegistrationId(envelope.data.registration_id);
      setStep(3);
    },
    onError: (error: unknown) => {
      const apiError = toApiError(error);
      if (apiError?.code === ERROR_CODES.DUPLICATE_MSISDN) {
        // The duplicate is an MSISDN-field error — return to Step 1 to show it inline.
        setStep(1);
        setStepError("This mobile number is already registered.");
      } else {
        setStepError(
          apiError?.message ?? "Registration failed. Please try again.",
        );
      }
    },
  });

  const setField = <K extends keyof FormState>(
    key: K,
    value: FormState[K],
  ): void => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setStepError("");
  };

  const validateStep1 = (): boolean => {
    if (!form.full_name.trim()) return invalidate("Full name is required.");
    if (!EMAIL_RE.test(form.email))
      return invalidate("A valid email is required.");
    if (!MSISDN_RE.test(form.msisdn))
      return invalidate("MSISDN must be 10-15 digits.");
    if (!MSISDN_RE.test(form.alternate_mobile))
      return invalidate("Alternate mobile must be 10-15 digits.");
    return true;
  };

  const validateStep2 = (): boolean => {
    if (!form.date_of_birth) return invalidate("Date of birth is required.");
    if (!form.address_line1.trim())
      return invalidate("Address line 1 is required.");
    if (!form.city.trim() || !form.state.trim() || !form.pin_code.trim())
      return invalidate("Full address is required.");
    if (!form.id_proof_number.trim())
      return invalidate("ID proof number is required.");
    if (!form.consent)
      return invalidate("Consent is required to submit the TRAI CAF.");
    return true;
  };

  const invalidate = (message: string): boolean => {
    setStepError(message);
    return false;
  };

  const handleNext = (): void => {
    if (step === 1 && validateStep1()) setStep(2);
  };

  const handleBack = (): void => {
    setStepError("");
    setStep((s) => (s > 1 ? s - 1 : s) as Step);
  };

  const handleSubmit = (event: FormEvent): void => {
    event.preventDefault();
    if (mutation.isPending) return;
    if (!validateStep2()) return;
    const payload: RegisterPayload = { ...form };
    mutation.mutate(payload);
  };

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-neutral-900">
          Subscriber Registration
        </h1>
        <p className="mt-1 text-sm text-neutral-600">
          Step {step} of 3 —{" "}
          {step === 1
            ? "Personal details"
            : step === 2
              ? "TRAI CAF"
              : "Registration complete"}
        </p>
      </header>

      {step === 3 ? (
        <Card>
          <CardSection title="Your Registration ID">
            <p className="mb-2 text-sm text-neutral-600">
              Use this ID to log in once your SIM is active.
            </p>
            <p
              role="textbox"
              aria-label="Registration ID"
              className="rounded-md bg-neutral-100 px-4 py-3 font-mono text-3xl font-semibold text-neutral-900"
            >
              {registrationId}
            </p>
            <div className="mt-3">
              <Badge variant="pending">
                {mutation.data?.data.status ?? "REGISTRATION_COMPLETE"}
              </Badge>
            </div>
          </CardSection>

          <CardSection title="Verify your mobile">
            <p className="mb-3 text-sm text-neutral-600">
              An OTP was sent to your alternate mobile number. Enter it to
              verify (verification completes the login flow in Story 1.8).
            </p>
            <input
              aria-label="One-time passcode"
              className="mb-3 w-full rounded-md border border-neutral-200 px-3 py-2 font-mono text-base"
              inputMode="numeric"
              maxLength={6}
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              placeholder="6-digit code"
            />
            <Button type="button" variant="primary" disabled={otp.length !== 6}>
              Verify &amp; Complete
            </Button>
          </CardSection>
        </Card>
      ) : (
        <Card>
          <form onSubmit={handleSubmit} noValidate>
            {step === 1 && (
              <CardSection title="Personal details">
                <Field
                  label="Full name"
                  value={form.full_name}
                  onChange={(v) => setField("full_name", v)}
                />
                <Field
                  label="Email"
                  value={form.email}
                  type="email"
                  onChange={(v) => setField("email", v)}
                />
                <Field
                  label="MSISDN (mobile to activate)"
                  value={form.msisdn}
                  inputMode="numeric"
                  onChange={(v) => setField("msisdn", v)}
                />
                <Field
                  label="Alternate mobile (for OTP)"
                  value={form.alternate_mobile}
                  inputMode="numeric"
                  onChange={(v) => setField("alternate_mobile", v)}
                />
              </CardSection>
            )}

            {step === 2 && (
              <>
                <CardSection title="TRAI Customer Acquisition Form">
                  <Field
                    label="Date of birth"
                    value={form.date_of_birth}
                    type="date"
                    onChange={(v) => setField("date_of_birth", v)}
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
                </CardSection>

                <CardSection title="ID proof">
                  <label
                    className="mb-1 block text-sm font-medium text-neutral-800"
                    htmlFor="id_proof_type"
                  >
                    ID proof type
                  </label>
                  <select
                    id="id_proof_type"
                    className="mb-3 w-full rounded-md border border-neutral-200 px-3 py-2 text-base"
                    value={form.id_proof_type}
                    onChange={(e) =>
                      setField(
                        "id_proof_type",
                        e.target.value as FormState["id_proof_type"],
                      )
                    }
                  >
                    {ID_PROOF_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <Field
                    label="ID proof number"
                    value={form.id_proof_number}
                    onChange={(v) => setField("id_proof_number", v)}
                  />
                  <label className="mt-3 flex items-center gap-2 text-sm text-neutral-800">
                    <input
                      type="checkbox"
                      checked={form.consent}
                      onChange={(e) => setField("consent", e.target.checked)}
                    />
                    I consent to data processing per the TRAI CAF.
                  </label>
                </CardSection>
              </>
            )}

            {stepError && (
              <p role="alert" className="mb-4 text-sm text-danger-600">
                {stepError}
              </p>
            )}

            <div className="flex items-center justify-between">
              {step === 2 ? (
                <Button type="button" variant="secondary" onClick={handleBack}>
                  Back
                </Button>
              ) : (
                <span />
              )}
              {step === 1 ? (
                <Button type="button" variant="primary" onClick={handleNext}>
                  Next
                </Button>
              ) : (
                <Button
                  type="submit"
                  variant="primary"
                  disabled={mutation.isPending}
                >
                  {mutation.isPending ? "Submitting…" : "Submit registration"}
                </Button>
              )}
            </div>
          </form>
        </Card>
      )}
    </main>
  );
}

interface FieldProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly type?: string;
  readonly inputMode?: "numeric" | "text";
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  inputMode = "text",
}: FieldProps) {
  const fieldId = label
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "");
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
        inputMode={inputMode}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export { Register };
