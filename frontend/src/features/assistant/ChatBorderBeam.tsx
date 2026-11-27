import { memo, useId, type CSSProperties } from 'react';

const perimeter = 1000;
const beamLength = perimeter * 0.6;
const segmentLength = 10;
const segmentCount = beamLength / segmentLength;
const halfOverlap = 0.15;

const segments = Array.from({ length: segmentCount }, (_, index) => {
  const fromEdge = (Math.min(index, segmentCount - 1 - index) + 0.5) / segmentCount;
  const intensity = Math.sin(Math.PI * fromEdge);
  const mix = `${intensity * 100}%`;
  const shade = `color-mix(in oklab, var(--chat-beam-tail), var(--chat-beam-color) ${mix})`;
  const tint = `color-mix(in oklab, var(--chat-beam-color), var(--chat-beam-peak) ${mix})`;
  const overlapBefore = index === 0 ? 0 : halfOverlap;
  const overlapAfter = index === segmentCount - 1 ? 0 : halfOverlap;

  return {
    offset: -(140 + index * segmentLength - overlapBefore),
    length: segmentLength + overlapBefore + overlapAfter,
    width: 0.45 + 1.55 * intensity,
    opacity: 0.92 * intensity ** 1.7,
    color: `color-mix(in oklab, ${shade}, ${tint} ${mix})`,
  };
});

export const ChatBorderBeam = memo(function ChatBorderBeam() {
  const glowId = useId();
  // pathLength makes each dash cover the same share of the actual rounded perimeter.
  return (
    <svg className="chat-input-beam" aria-hidden="true" focusable="false">
      <defs>
        <filter id={glowId} colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="nearGlow" />
          <feGaussianBlur in="SourceGraphic" stdDeviation="10" />
          <feComponentTransfer result="farGlow">
            <feFuncA type="linear" slope="1.8" />
          </feComponentTransfer>
          <feMerge>
            <feMergeNode in="farGlow" />
            <feMergeNode in="nearGlow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g filter={`url(#${glowId})`}>
        {segments.map(({ offset, length, width, opacity, color }) => (
          <rect
            key={offset}
            pathLength={perimeter}
            strokeDasharray={`${length} ${perimeter - length}`}
            strokeWidth={width}
            opacity={opacity}
            style={{
              '--chat-beam-offset': `${offset}px`,
              '--chat-beam-segment-color': color,
            } as CSSProperties}
          />
        ))}
      </g>
    </svg>
  );
});
