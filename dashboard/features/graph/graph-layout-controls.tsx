'use client';

import {
  DEFAULT_SPACING,
  MAX_SPACING,
  MIN_SPACING,
  SPACING_STEP,
} from './graph-layout';

type GraphLayoutControlsProps = {
  snapToGrid: boolean;
  onSnapToGridChange: (enabled: boolean) => void;
  alignLabel: string;
  alignDisabled?: boolean;
  onAlign: () => void | Promise<void>;
  spacing: number;
  onSpacingChange: (spacing: number) => void;
};

export function GraphLayoutControls({
  snapToGrid,
  onSnapToGridChange,
  alignLabel,
  alignDisabled = false,
  onAlign,
  spacing,
  onSpacingChange,
}: GraphLayoutControlsProps) {
  const adjustSpacing = (delta: number) => {
    onSpacingChange(Math.min(
      MAX_SPACING,
      Math.max(MIN_SPACING, spacing + delta),
    ));
  };

  return (
    <div className="graph-layout-control">
      <div className="graph-layout-control__title">Map layout</div>
      <button
        type="button"
        className="graph-layout-control__snap"
        aria-pressed={snapToGrid}
        onClick={() => onSnapToGridChange(!snapToGrid)}
      >
        <span>Snap to grid</span>
        <span
          className={[
            'graph-layout-control__switch',
            snapToGrid ? 'graph-layout-control__switch--on' : '',
          ].filter(Boolean).join(' ')}
          aria-hidden="true"
        >
          <span />
        </span>
      </button>
      <button
        type="button"
        className="graph-layout-control__align"
        disabled={alignDisabled}
        onClick={() => void onAlign()}
      >
        {alignLabel}
      </button>
      <div className="graph-spacing-control">
        <div className="graph-spacing-control__heading">
          <span>Spacing</span>
          <button
            type="button"
            onClick={() => onSpacingChange(DEFAULT_SPACING)}
            title="Reset spacing to 100%"
          >
            {spacing}%
          </button>
        </div>
        <div className="graph-spacing-control__controls">
          <button
            type="button"
            aria-label="Decrease map spacing"
            disabled={spacing <= MIN_SPACING}
            onClick={() => adjustSpacing(-SPACING_STEP)}
          >
            −
          </button>
          <input
            type="range"
            aria-label="Map spacing"
            min={MIN_SPACING}
            max={MAX_SPACING}
            step={SPACING_STEP}
            value={spacing}
            onChange={(event) => onSpacingChange(Number(event.target.value))}
          />
          <button
            type="button"
            aria-label="Increase map spacing"
            disabled={spacing >= MAX_SPACING}
            onClick={() => adjustSpacing(SPACING_STEP)}
          >
            +
          </button>
        </div>
      </div>
    </div>
  );
}
