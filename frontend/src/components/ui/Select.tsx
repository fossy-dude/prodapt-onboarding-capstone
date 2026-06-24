import { type SelectHTMLAttributes, forwardRef } from "react";

interface SelectOption {
  readonly value: string;
  readonly label: string;
  readonly disabled?: boolean;
}

interface SelectProps extends Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "size"
> {
  readonly label?: string;
  readonly error?: string;
  readonly size?: "sm" | "md" | "lg";
  readonly options: readonly SelectOption[];
  readonly placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      label,
      error,
      size = "md",
      options,
      placeholder,
      className = "",
      ...props
    },
    ref,
  ) => {
    const sizeClasses = {
      sm: "px-3 py-1.5 text-sm",
      md: "px-4 py-2 text-base",
      lg: "px-5 py-3 text-lg",
    };

    const baseClasses =
      "w-full rounded-md border border-gray-300 bg-white focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:bg-gray-100 disabled:cursor-not-allowed";
    const errorClasses = error
      ? "border-red-500 focus:border-red-500 focus:ring-red-500/20"
      : "";

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label className="text-sm font-medium text-gray-700">
            {label}
            {props.required && <span className="ml-1 text-red-500">*</span>}
          </label>
        )}
        <select
          ref={ref}
          className={`${baseClasses} ${sizeClasses[size]} ${errorClasses} ${className}`.trim()}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
    );
  },
);

Select.displayName = "Select";
