import { memo, type CSSProperties } from 'react';

const perimeter = 1000;
const segmentCount = 26;
const segmentLength = 10;

const segments = Array.from({ length: segmentCount }, (_, index) => {
  const alongBeam = (index + 0.5) / segmentCount;
  const peakToBody = Math.min(1, alongBeam / 0.24);
  const bodyToTail = Math.max(0, (alongBeam - 0.24) / 0.76);
  const color = peakToBody < 1
    ? `color-mix(in srgb, var(--chat-beam-peak), var(--chat-beam-color) ${peakToBody * 100}%)`
    : `color-mix(in srgb, var(--chat-beam-color), var(--chat-beam-tail) ${bodyToTail * 100}%)`;

  return {
    offset: -(140 + index * segmentLength),
    opacity: Math.min(1, alongBeam / 0.14) * (1 - alongBeam) ** 1.2,
    color,
  };
});

export const ChatBorderBeam = memo(function ChatBorderBeam() {
  // pathLength makes each dash cover the same share of the actual rounded perimeter.
  const dashLength = segmentLength + 0.3;
  return (
    <svg className="chat-input-beam" aria-hidden="true" focusable="false">
      {segments.map(({ offset, opacity, color }) => (
        <rect
          key={offset}
          pathLength={perimeter}
          strokeDasharray={`${dashLength} ${perimeter - dashLength}`}
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
