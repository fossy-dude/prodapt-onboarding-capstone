/**
 * Recharge flow component (Story 3.5).
 *
 * 3-step recharge flow:
 * 1. Plan selection (preselect from ?plan_id= if provided)
 * 2. Payment method selection (saved methods + add new option)
 * 3. Confirmation (new balance + plan activation + receipt link)
 */

import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { uuidv7 } from "uuidv7";
import { Button, Card, Input, Modal, Select } from "../../components/ui";
import { useRecharge } from "../../hooks/useRecharge";
import { usePaymentMethods } from "../../hooks/usePaymentMethods";
import { usePlans } from "../../hooks/usePlans";
import { tokenizeCard } from "../../lib/tokenize";
import type {
  PaymentMethod,
  PaymentMethodType,
} from "../../types/payment-method";
import type { PlanCatalogueItem } from "../../types/plan";

type Step = 1 | 2 | 3;

interface RechargeState {
  selectedPlan: PlanCatalogueItem | null;
  selectedPaymentMethod: PaymentMethod | null;
  transactionResult: {
    transaction_id: string;
    new_balance_paise: number;
    plan_activation_timestamp: string;
    receipt_url: string;
  } | null;
}

export function Recharge() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    data: plans,
    isLoading: plansLoading,
    isError: plansError,
  } = usePlans();
  const {
    data: paymentMethods,
    isLoading: paymentMethodsLoading,
    isError: paymentMethodsError,
  } = usePaymentMethods();
  const rechargeMutation = useRecharge();

  const [step, setStep] = useState<Step>(1);
  const [state, setState] = useState<RechargeState>({
    selectedPlan: null,
    selectedPaymentMethod: null,
    transactionResult: null,
  });

  // Add new payment method state
  const [showAddPaymentModal, setShowAddPaymentModal] = useState(false);
  const [newPaymentMethodType, setNewPaymentMethodType] =
    useState<PaymentMethodType>("CREDIT_CARD");
  const [newPaymentCardNumber, setNewPaymentCardNumber] = useState("");
  const [newPaymentDisplayLabel, setNewPaymentDisplayLabel] = useState("");

  // Error state for user-facing feedback
  const [rechargeError, setRechargeError] = useState<string | null>(null);

  // Combined loading and error states to prevent race conditions
  const isLoading = plansLoading || paymentMethodsLoading;
  const hasError = plansError || paymentMethodsError;

  // Preselect plan from URL if provided - using useEffect to prevent race conditions
  useEffect(() => {
    const planId = searchParams.get("plan_id");
    if (planId && plans && !state.selectedPlan) {
      const preselectedPlan = plans.find((p) => p.id === planId);
      if (preselectedPlan) {
        setState((prev) => ({ ...prev, selectedPlan: preselectedPlan }));
      }
    }
  }, [searchParams, plans, state.selectedPlan]);

  const handlePlanSelect = (plan: PlanCatalogueItem) => {
    setState((prev) => ({ ...prev, selectedPlan: plan }));
    setStep(2);
  };

  const handlePaymentMethodSelect = (paymentMethod: PaymentMethod) => {
    setState((prev) => ({ ...prev, selectedPaymentMethod: paymentMethod }));
    setStep(3);
  };

  const handleAddPaymentMethod = async () => {
    // Validate card number before tokenization
    if (!newPaymentCardNumber || newPaymentCardNumber.length < 13) {
      setRechargeError("Please enter a valid card number");
      return;
    }

    // Tokenize card before sending to API (FR-64 compliance)
    const { token, last4 } = tokenizeCard(newPaymentCardNumber);

    // NOTE: This is a placeholder implementation. In production, this should call
    // the proper addPaymentMethod API to create a persistent payment method.
    // For now, we create a temporary method with a UUID-based ID instead of
    // temp-${Date.now()} to avoid conflicts and follow UUID conventions.
    const newMethod: PaymentMethod = {
      id: `temp-${uuidv7()}`, // Use UUID7 instead of Date.now() for better uniqueness
      subscriber_id: "",
      type: newPaymentMethodType,
      token,
      display_label: newPaymentDisplayLabel || `•••• ${last4}`,
      is_default: false,
    };

    setState((prev) => ({ ...prev, selectedPaymentMethod: newMethod }));
    setShowAddPaymentModal(false);
    setStep(3);

    // Reset form
    setNewPaymentCardNumber("");
    setNewPaymentDisplayLabel("");
    setRechargeError(null);
  };

  const handleConfirmRecharge = async () => {
    if (!state.selectedPlan || !state.selectedPaymentMethod) return;

    const idempotencyKey = uuidv7();
    setRechargeError(null); // Clear previous error
    try {
      const result = await rechargeMutation.mutateAsync({
        plan_id: state.selectedPlan.id,
        payment_method_id: state.selectedPaymentMethod.id,
        idempotency_key: idempotencyKey,
      });

      setState((prev) => ({ ...prev, transactionResult: result }));
    } catch (error) {
      console.error("Recharge failed:", error);
      // Set user-facing error message
      setRechargeError(
        "Recharge failed. Please check your payment details or try a different payment method.",
      );
    }
  };

  const handleBackToDashboard = () => {
    navigate("/subscriber/dashboard");
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-lg text-gray-600">Loading...</div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="text-lg text-red-600 mb-2">Failed to load data</div>
          <p className="text-sm text-gray-600">
            Please refresh the page or try again later.
          </p>
        </div>
      </div>
    );
  }

  // Step 1: Plan Selection
  if (step === 1) {
    return (
      <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Select a Plan</h1>
          <p className="mt-2 text-sm text-gray-600">
            Choose a plan that suits your needs
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {plans
            ?.filter((plan) => plan.is_active !== false)
            .map((plan) => (
              <div
                key={plan.id}
                onClick={() => handlePlanSelect(plan)}
                className={`cursor-pointer transition-colors hover:border-blue-500 rounded-lg border border-neutral-200 bg-neutral-50 p-6 shadow-sm ${
                  state.selectedPlan?.id === plan.id
                    ? "border-blue-500 ring-2 ring-blue-500/20"
                    : ""
                }`}
              >
                <div className="space-y-3 p-6">
                  <h3 className="text-lg font-semibold text-gray-900">
                    {plan.name}
                  </h3>
                  <div className="text-2xl font-bold text-gray-900">
                    ₹{(plan.price_paise / 100).toFixed(2)}
                  </div>
                  <ul className="space-y-1 text-sm text-gray-600">
                    <li>Validity: {plan.validity_days} days</li>
                    {plan.data_gb !== null && <li>Data: {plan.data_gb} GB</li>}
                    {plan.voice_minutes !== null && (
                      <li>Voice: {plan.voice_minutes} min</li>
                    )}
                    {plan.sms_count !== null && <li>SMS: {plan.sms_count}</li>}
                  </ul>
                  <Button
                    className="w-full"
                    variant={
                      state.selectedPlan?.id === plan.id
                        ? "primary"
                        : "secondary"
                    }
                  >
                    {state.selectedPlan?.id === plan.id ? "Selected" : "Select"}
                  </Button>
                </div>
              </div>
            ))}
        </div>
      </div>
    );
  }

  // Step 2: Payment Method Selection
  if (step === 2) {
    return (
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
        <div>
          <button
            onClick={() => setStep(1)}
            className="text-sm text-blue-600 hover:text-blue-700"
          >
            ← Back to plans
          </button>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            Select Payment Method
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            Paying for {state.selectedPlan?.name} (₹
            {((state.selectedPlan?.price_paise || 0) / 100).toFixed(2)})
          </p>
        </div>

        <Card>
          <div className="space-y-4 p-6">
            {paymentMethods && paymentMethods.length > 0 ? (
              paymentMethods.map((method) => (
                <div
                  key={method.id}
                  className={`cursor-pointer rounded-lg border p-4 transition-colors hover:border-blue-500 ${
                    state.selectedPaymentMethod?.id === method.id
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-200"
                  }`}
                  onClick={() => handlePaymentMethodSelect(method)}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-medium text-gray-900">
                        {method.display_label}
                      </div>
                      <div className="text-sm text-gray-600">
                        {method.type.replace("_", " ")}
                      </div>
                    </div>
                    {method.is_default && (
                      <span className="text-xs text-gray-500">Default</span>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center text-gray-600">
                No saved payment methods
              </div>
            )}

            <Button
              className="w-full"
              variant="secondary"
              onClick={() => setShowAddPaymentModal(true)}
            >
              + Add New Payment Method
            </Button>
          </div>
        </Card>

        {/* Add Payment Method Modal */}
        <Modal
          isOpen={showAddPaymentModal}
          onClose={() => setShowAddPaymentModal(false)}
          title="Add Payment Method"
        >
          <div className="space-y-4">
            <Select
              label="Payment Method Type"
              value={newPaymentMethodType}
              onChange={(e) =>
                setNewPaymentMethodType(e.target.value as PaymentMethodType)
              }
              options={[
                { value: "CREDIT_CARD", label: "Credit Card" },
                { value: "UPI", label: "UPI" },
                { value: "NET_BANKING", label: "Net Banking" },
                { value: "MOBILE_WALLET", label: "Mobile Wallet" },
              ]}
            />

            {newPaymentMethodType === "CREDIT_CARD" && (
              <>
                <Input
                  label="Card Number"
                  value={newPaymentCardNumber}
                  onChange={(e) => setNewPaymentCardNumber(e.target.value)}
                  placeholder="4242 4242 4242 4242"
                  required
                />
                <Input
                  label="Display Label (optional)"
                  value={newPaymentDisplayLabel}
                  onChange={(e) => setNewPaymentDisplayLabel(e.target.value)}
                  placeholder="My Personal Card"
                />
              </>
            )}

            {newPaymentMethodType !== "CREDIT_CARD" && (
              <Input
                label="Display Label"
                value={newPaymentDisplayLabel}
                onChange={(e) => setNewPaymentDisplayLabel(e.target.value)}
                placeholder="My UPI ID"
                required
              />
            )}

            <div className="flex gap-3">
              <Button
                className="flex-1"
                variant="secondary"
                onClick={() => setShowAddPaymentModal(false)}
              >
                Cancel
              </Button>
              <Button
                className="flex-1"
                onClick={handleAddPaymentMethod}
                disabled={rechargeMutation.isPending}
              >
                Add Method
              </Button>
            </div>
          </div>
        </Modal>
      </div>
    );
  }

  // Step 3: Confirmation
  if (step === 3) {
    if (state.transactionResult) {
      // Success screen
      return (
        <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
          <Card>
            <div className="space-y-4 p-6 text-center">
              <div className="text-6xl">✅</div>
              <h1 className="text-2xl font-bold text-gray-900">
                Recharge Successful!
              </h1>
              <p className="text-gray-600">Your wallet has been topped up</p>

              <div className="mt-6 space-y-2 rounded-lg bg-gray-50 p-4 text-left">
                <div className="flex justify-between">
                  <span className="text-gray-600">Transaction ID:</span>
                  <span className="font-mono text-sm">
                    {state.transactionResult.transaction_id}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">New Balance:</span>
                  <span className="font-semibold">
                    ₹
                    {(state.transactionResult.new_balance_paise / 100).toFixed(
                      2,
                    )}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Plan Activated:</span>
                  <span className="font-semibold">
                    {state.selectedPlan?.name}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Activation Time:</span>
                  <span className="text-sm">
                    {new Date(
                      state.transactionResult.plan_activation_timestamp,
                    ).toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="flex gap-3">
                <a
                  href={state.transactionResult.receipt_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  download
                  className="flex-1"
                >
                  <Button className="w-full" variant="secondary">
                    Download Receipt
                  </Button>
                </a>
                <Button className="flex-1" onClick={handleBackToDashboard}>
                  Back to Dashboard
                </Button>
              </div>
            </div>
          </Card>
        </div>
      );
    }

    // Confirmation screen before submitting
    return (
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
        <div>
          <button
            onClick={() => setStep(2)}
            className="text-sm text-blue-600 hover:text-blue-700"
          >
            ← Back to payment methods
          </button>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            Confirm Recharge
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            Review your recharge details before confirming
          </p>
        </div>

        <Card>
          <div className="space-y-4 p-6">
            <div className="rounded-lg bg-gray-50 p-4">
              <h3 className="font-semibold text-gray-900">Plan Details</h3>
              <div className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Plan:</span>
                  <span className="font-medium">
                    {state.selectedPlan?.name}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Validity:</span>
                  <span>{state.selectedPlan?.validity_days} days</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Amount:</span>
                  <span className="font-semibold">
                    ₹{((state.selectedPlan?.price_paise || 0) / 100).toFixed(2)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-gray-50 p-4">
              <h3 className="font-semibold text-gray-900">Payment Method</h3>
              <div className="mt-2 text-sm">
                <div className="font-medium">
                  {state.selectedPaymentMethod?.display_label}
                </div>
                <div className="text-gray-600">
                  {state.selectedPaymentMethod?.type.replace("_", " ")}
                </div>
              </div>
            </div>

            <Button
              className="w-full"
              onClick={handleConfirmRecharge}
              disabled={rechargeMutation.isPending}
            >
              {rechargeMutation.isPending
                ? "Processing..."
                : "Confirm Recharge"}
            </Button>

            {rechargeError && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                {rechargeError}
              </div>
            )}
          </div>
        </Card>
      </div>
    );
  }

  return null;
}
