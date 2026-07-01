import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Badge, Button, Card, CardSection } from "../../components/ui";
import { registerSubscriber, verifyLoginOtp, toApiError } from "../../lib/api";
import { saveToken, saveRefreshToken } from "../../lib/auth";
import type { RegisterPayload } from "../../types/subscriber";

const ID_PROOF_TYPES = ["Aadhaar", "PAN", "Passport", "Voter ID"] as const;
const MSISDN_RE = /^\d{10,15}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface FormState {
  full_name: string;
  email: string;
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

type FieldErrors = Partial<Record<keyof FormState, string>>;

const EMPTY_FORM: FormState = {
  full_name: "",
  email: "",
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
 *           MSISDN is NOT collected here — it is auto-generated at SIM activation.
 * Step 2 — TRAI CAF fields; submit creates the registration.
 * Step 3 — Registration ID display + OTP entry.
 */
function Register() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [registrationId, setRegistrationId] = useState<string>("");
  const [otp, setOtp] = useState<string>("");
  const [stepError, setStepError] = useState<string>("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const mutation = useMutation({
    mutationFn: registerSubscriber,
    onSuccess: (envelope) => {
      setRegistrationId(envelope.data.registration_id);
      setFieldErrors({});
      setStepError("");
      setStep(3);
    },
    onError: (error: unknown) => {
      const apiError = toApiError(error);
      setStepError(
        apiError?.message ?? "Registration failed. Please try again.",
      );
    },
  });

  const verifyMutation = useMutation({
    mutationFn: ({ id, code }: { id: string; code: string }) =>
      verifyLoginOtp(id, code),
    onSuccess: (tokens) => {
      saveToken(tokens.access_token);
      if (tokens.refresh_token) saveRefreshToken(tokens.refresh_token);
      navigate("/subscriber/activate", { replace: true });
    },
    onError: (error: unknown) => {
      const apiError = toApiError(error);
      setStepError(
        apiError?.message ?? "OTP verification failed. Please try again.",
      );
    },
  });

  const setField = <K extends keyof FormState>(
    key: K,
    value: FormState[K],
  ): void => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (fieldErrors[key]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  };

  const validateStep1 = (): boolean => {
    const errors: FieldErrors = {};
    if (!form.full_name.trim()) errors.full_name = "Required";
    if (!EMAIL_RE.test(form.email)) errors.email = "Valid email required";
    if (!MSISDN_RE.test(form.alternate_mobile))
      errors.alternate_mobile = "10–15 digits";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validateStep2 = (): boolean => {
    const errors: FieldErrors = {};
    if (!form.date_of_birth) errors.date_of_birth = "Required";
    if (!form.address_line1.trim()) errors.address_line1 = "Required";
    if (!form.city.trim()) errors.city = "Required";
    if (!form.state.trim()) errors.state = "Required";
    if (!form.pin_code.trim()) errors.pin_code = "Required";
    if (!form.id_proof_number.trim()) errors.id_proof_number = "Required";
    setFieldErrors(errors);
    if (!form.consent) {
      setStepError("Consent is required to submit the TRAI CAF.");
      return false;
    }
    setStepError("");
    return Object.keys(errors).length === 0;
  };

  const handleNext = (): void => {
    if (step === 1 && validateStep1()) {
      setFieldErrors({});
      setStep(2);
    }
  };

  const handleBack = (): void => {
    setStepError("");
    setFieldErrors({});
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
            {stepError && (
              <p role="alert" className="mb-3 text-sm text-danger-600">
                {stepError}
              </p>
            )}
            <Button
              type="button"
              variant="primary"
              disabled={otp.length !== 6 || verifyMutation.isPending}
              onClick={() =>
                verifyMutation.mutate({ id: registrationId, code: otp })
              }
            >
              {verifyMutation.isPending ? "Verifying…" : "Verify & Complete"}
            </Button>
          </CardSection>
        </Card>
      ) : (
        <Card>
          <form onSubmit={handleSubmit} noValidate>
            {step === 1 && (
              <CardSection title="Personal details">
                <p className="mb-4 rounded-md bg-blue-50 px-4 py-3 text-sm text-blue-700">
                  A mobile number will be automatically assigned when your SIM
                  is activated.
                </p>
                <Field
                  label="Full name"
                  value={form.full_name}
                  onChange={(v) => setField("full_name", v)}
                  required
                  error={fieldErrors.full_name}
                />
                <Field
                  label="Email"
                  value={form.email}
                  type="email"
                  onChange={(v) => setField("email", v)}
                  required
                  error={fieldErrors.email}
                />
                <Field
                  label="Alternate mobile (for OTP)"
                  value={form.alternate_mobile}
                  inputMode="numeric"
                  onChange={(v) => setField("alternate_mobile", v)}
                  required
                  error={fieldErrors.alternate_mobile}
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
                    required
                    error={fieldErrors.date_of_birth}
                  />
                  <Field
                    label="Address line 1"
                    value={form.address_line1}
                    onChange={(v) => setField("address_line1", v)}
                    required
                    error={fieldErrors.address_line1}
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
                      required
                      error={fieldErrors.city}
                    />
                    <Field
                      label="State"
                      value={form.state}
                      onChange={(v) => setField("state", v)}
                      required
                      error={fieldErrors.state}
                    />
                  </div>
                  <Field
                    label="PIN code"
                    value={form.pin_code}
                    onChange={(v) => setField("pin_code", v)}
                    required
                    error={fieldErrors.pin_code}
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
                    required
                    error={fieldErrors.id_proof_number}
                  />
                  <label className="mt-3 flex items-center gap-2 text-sm text-neutral-800">
                    <input
                      type="checkbox"
                      checked={form.consent}
                      onChange={(e) => {
                        setField("consent", e.target.checked);
                        if (e.target.checked) setStepError("");
                      }}
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
  readonly required?: boolean;
  readonly error?: string;
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  inputMode = "text",
  required,
  error,
}: FieldProps) {
  const fieldId = label
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "");
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-baseline justify-between">
        <div className="flex items-baseline gap-0.5">
          <label
            className="text-sm font-medium text-neutral-800"
            htmlFor={fieldId}
          >
            {label}
          </label>
          {required && (
            <span className="text-xs text-red-500" aria-hidden="true">
              *
            </span>
          )}
        </div>
        {error && (
          <span className="text-xs font-medium text-danger-600" role="alert">
            {error}
          </span>
        )}
      </div>
      <input
        id={fieldId}
        className={`w-full rounded-md border px-3 py-2 text-base transition-colors ${
          error
            ? "border-red-400 bg-red-50 ring-1 ring-red-300 focus:outline-none focus:ring-2 focus:ring-red-400"
            : "border-neutral-200 focus:outline-none focus:ring-2 focus:ring-brand-400"
        }`}
        type={type}
        inputMode={inputMode}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export { Register };
