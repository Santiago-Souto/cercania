"use client";
// Phone field with a searchable country picker (react-phone-number-input + shadcn Popover/Command).
// The value is always E.164 ("+59899123456") or undefined, which is what the backend expects.
import * as React from "react";
import * as RPNInput from "react-phone-number-input";
import flags from "react-phone-number-input/flags";
import es from "react-phone-number-input/locale/es";
import { ChevronsUpDownIcon } from "lucide-react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type PhoneInputProps = Omit<React.ComponentProps<"input">, "onChange" | "value" | "ref"> &
  Omit<RPNInput.Props<typeof RPNInput.default>, "onChange"> & {
    onChange?: (value: RPNInput.Value | undefined) => void;
  };

function PhoneInput({ className, onChange, defaultCountry = "UY", ...props }: PhoneInputProps) {
  return (
    <RPNInput.default
      className={cn("flex", className)}
      flagComponent={FlagComponent}
      countrySelectComponent={CountrySelect}
      inputComponent={NumberInput}
      labels={es}
      defaultCountry={defaultCountry}
      smartCaret={false}
      onChange={(value) => onChange?.(value || undefined)}
      {...props}
    />
  );
}

function NumberInput({ className, ...props }: React.ComponentProps<"input">) {
  return <Input className={cn("rounded-s-none rounded-e-lg", className)} {...props} />;
}

type CountryEntry = { label: string; value: RPNInput.Country | undefined };

function CountrySelect({
  disabled,
  value: selected,
  options,
  onChange,
}: {
  disabled?: boolean;
  value: RPNInput.Country;
  options: CountryEntry[];
  onChange: (country: RPNInput.Country) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const countries = options.filter((o): o is { label: string; value: RPNInput.Country } => !!o.value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="h-auto gap-1 rounded-s-lg rounded-e-none border-r-0 bg-card px-3 focus:z-10"
          disabled={disabled}
          aria-label={selected ? `País: ${es[selected]}` : "Elegir país"}
        >
          <FlagComponent country={selected} countryName={selected ? es[selected] : ""} />
          <span className="text-sm text-muted-foreground">+{selected ? RPNInput.getCountryCallingCode(selected) : ""}</span>
          <ChevronsUpDownIcon className="size-4 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[300px] p-0" align="start">
        <Command filter={(value, search) => (fold(value).includes(fold(search)) ? 1 : 0)}>
          <CommandInput placeholder="Buscar país…" />
          <CommandList className="max-h-72">
            <CommandEmpty>No encontramos ese país.</CommandEmpty>
            <CommandGroup>
              {countries.map(({ value, label }) => (
                <CommandItem
                  key={value}
                  value={`${label} +${RPNInput.getCountryCallingCode(value)}`}
                  onSelect={() => {
                    onChange(value);
                    setOpen(false);
                  }}
                  data-checked={value === selected}
                >
                  <FlagComponent country={value} countryName={label} />
                  <span className="flex-1 text-sm">{label}</span>
                  <span className="text-sm text-muted-foreground">+{RPNInput.getCountryCallingCode(value)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Lowercase without accents, so "peru" finds "Perú". */
function fold(s: string) {
  return s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function FlagComponent({ country, countryName }: RPNInput.FlagProps) {
  const Flag = country ? flags[country] : undefined;
  return (
    <span className="flex h-4 w-6 shrink-0 overflow-hidden rounded-sm bg-muted [&>svg]:size-full!">
      {Flag && <Flag title={countryName} />}
    </span>
  );
}

export { PhoneInput };
