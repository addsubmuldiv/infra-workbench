import { memo, type CSSProperties } from 'react';

const perimeter = 1000;
const beamLength = perimeter * 2 / 5;
const segmentLength = 10;
const segmentCount = beamLength / segmentLength;
const halfOverlap = 0.15;

const segments = Array.from({ length: segmentCount }, (_, index) => {
  const fromEdge = (Math.min(index, segmentCount - 1 - index) + 0.5) / segmentCount;
  const intensity = Math.sin(Math.PI * fromEdge);
  const edgeToBody = Math.min(1, fromEdge / 0.2);
  const bodyToCenter = Math.max(0, (fromEdge - 0.2) / 0.3);
  const color = edgeToBody < 1
    ? `color-mix(in srgb, var(--chat-beam-tail), var(--chat-beam-color) ${edgeToBody * 100}%)`
    : `color-mix(in srgb, var(--chat-beam-color), var(--chat-beam-peak) ${bodyToCenter * 100}%)`;
  const overlapBefore = index === 0 ? 0 : halfOverlap;
  const overlapAfter = index === segmentCount - 1 ? 0 : halfOverlap;

  return {
    offset: -(140 + index * segmentLength - overlapBefore),
    length: segmentLength + overlapBefore + overlapAfter,
    width: 0.45 + 1.55 * intensity,
    opacity: 0.92 * intensity ** 1.7,
    color,
  };
});

export const ChatBorderBeam = memo(function ChatBorderBeam() {
  // pathLength makes each dash cover the same share of the actual rounded perimeter.
  return (
    <svg className="chat-input-beam" aria-hidden="true" focusable="false">
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
    </svg>
  );
});
