import { roboticsArmExample, roboticsPositionExampleRange } from "@/lib/robotics-arm-example";

const episodes = Array.from(new Set(roboticsArmExample.map((row) => row.episode_id))).map((id) => ({
  id,
  samples: roboticsArmExample.filter((row) => row.episode_id === id),
}));

const sampleCount = roboticsArmExample.length;
const [rangeMin, rangeMax] = roboticsPositionExampleRange;
const positionValues = roboticsArmExample.map((row) => row.joint_1_position);
const inRangeCount = positionValues.filter((value) => value >= rangeMin && value <= rangeMax).length;

const chart = {
  width: 620,
  height: 250,
  left: 54,
  right: 548,
  top: 22,
  bottom: 180,
  min: -1.8,
  max: 1.8,
  gap: 56,
};
const segmentWidth = (chart.right - chart.left - chart.gap) / episodes.length;
const y = (value: number) =>
  chart.top + ((chart.max - value) / (chart.max - chart.min)) * (chart.bottom - chart.top);
const x = (episodeIndex: number, sampleIndex: number, count: number) =>
  chart.left + episodeIndex * (segmentWidth + chart.gap) +
  (count > 1 ? (sampleIndex / (count - 1)) * segmentWidth : 0);

export function HeroSignalChart() {
  const description = `Built-in playground arm example. ${sampleCount} joint 1 position samples across ${episodes.map((episode) => episode.id).join(" and ")} episodes, shown against an example range of ${rangeMin} to ${rangeMax} radians. ${inRangeCount} of ${sampleCount} sample values are within the displayed range. This is sample data, not a live robot feed.`;

  return (
    <figure className="hero-signal-chart" aria-labelledby="hero-signal-title">
      <div className="hero-chart-card">
        <div className="hero-chart-header">
          <div>
            <p className="hero-chart-eyebrow">Built-in arm example · {sampleCount} samples</p>
            <h2 id="hero-signal-title">Joint 1 position</h2>
          </div>
          <span className="hero-chart-result">
            <span aria-hidden="true">✓</span> {inRangeCount}/{sampleCount} in range
          </span>
        </div>

        <div className="hero-chart-legend" aria-hidden="true">
          <span><i className="hero-chart-legend-signal" />Recorded position</span>
          <span><i className="hero-chart-legend-limit" />Example limit</span>
        </div>

        <svg
          className="hero-chart-svg"
          viewBox={`0 0 ${chart.width} ${chart.height}`}
          role="img"
          aria-label={description}
        >
          <rect
            x={chart.left}
            y={y(rangeMax)}
            width={chart.right - chart.left}
            height={y(rangeMin) - y(rangeMax)}
            fill="#a95624"
            opacity="0.035"
          />
          {[rangeMax, 0, rangeMin].map((value) => (
            <line
              key={value}
              x1={chart.left}
              x2={chart.right}
              y1={y(value)}
              y2={y(value)}
              stroke={value === 0 ? "#d8d4ca" : "#a95624"}
              strokeWidth="1"
              strokeDasharray={value === 0 ? undefined : "4 5"}
            />
          ))}
          <line
            x1={chart.left}
            x2={chart.left}
            y1={chart.top}
            y2={chart.bottom}
            stroke="#d8d4ca"
            strokeWidth="1"
          />

          {[...episodes].map((episode, episodeIndex) => {
            const path = episode.samples.map((row, sampleIndex) => {
              const command = sampleIndex === 0 ? "M" : "L";
              return `${command}${x(episodeIndex, sampleIndex, episode.samples.length).toFixed(1)},${y(row.joint_1_position).toFixed(1)}`;
            }).join(" ");
            const center = chart.left + episodeIndex * (segmentWidth + chart.gap) + segmentWidth / 2;
            const start = x(episodeIndex, 0, episode.samples.length);
            const end = x(episodeIndex, episode.samples.length - 1, episode.samples.length);

            return (
              <g key={episode.id}>
                <path
                  d={path}
                  fill="none"
                  stroke="#24241f"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {episode.samples.map((row, sampleIndex) => (
                  <circle
                    key={`${episode.id}-${sampleIndex}`}
                    cx={x(episodeIndex, sampleIndex, episode.samples.length)}
                    cy={y(row.joint_1_position)}
                    r="3.5"
                    fill="#a95624"
                    stroke="#fbf9f4"
                    strokeWidth="1.5"
                  />
                ))}
                <text x={center} y="211" textAnchor="middle" className="hero-chart-episode">
                  {episode.id}
                </text>
                <text x={start} y="230" textAnchor="start" className="hero-chart-axis-label">0 s</text>
                <text x={end} y="230" textAnchor="end" className="hero-chart-axis-label">0.5 s</text>
              </g>
            );
          })}

          <text x="2" y={y(rangeMax) + 4} className="hero-chart-axis-label">+1.57</text>
          <text x="30" y={y(0) + 4} className="hero-chart-axis-label">0</text>
          <text x="2" y={y(rangeMin) + 4} className="hero-chart-axis-label">−1.57</text>
        </svg>

        <figcaption className="hero-chart-caption">
          <span>joint_1_position · radians</span>
          <span>Displayed range: −1.57 to +1.57</span>
        </figcaption>
        <p className="hero-chart-note">Playground sample values · not live robot data</p>
      </div>
    </figure>
  );
}
