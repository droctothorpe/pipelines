// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { Checkbox, FormControlLabel } from '@mui/material';
import Input from 'src/atoms/Input';

type Props = {
  name: string;
  kind?: string;
  value: string;
  required: boolean;
  onChange: (value: string) => void;
};

export default function NativeParameterInput({
  name,
  kind = 'String',
  value,
  required,
  onChange,
}: Props) {
  const nullable = kind.startsWith('Nullable');
  const base = nullable ? kind.slice('Nullable'.length) : kind;
  const none = nullable && value.trim() === 'null';
  let displayed = none ? '' : value;
  if (nullable && base === 'String' && !none) {
    try {
      displayed = JSON.parse(value);
    } catch {
      displayed = value;
    }
  }
  return (
    <div>
      <Input
        label={name}
        required={required}
        value={displayed}
        disabled={none}
        placeholder={none ? 'None' : undefined}
        variant='outlined'
        onChange={(event) =>
          onChange(
            nullable && base === 'String' ? JSON.stringify(event.target.value) : event.target.value,
          )
        }
      />
      {nullable && (
        <FormControlLabel
          label={`Use None for ${name}`}
          control={
            <Checkbox
              checked={none}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? 'null'
                    : base === 'String'
                      ? '""'
                      : base === 'Boolean'
                        ? 'false'
                        : base === 'List'
                          ? '[]'
                          : base === 'Dict'
                            ? '{}'
                            : '0',
                )
              }
            />
          }
        />
      )}
    </div>
  );
}
