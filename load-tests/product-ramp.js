import http from 'k6/http';
import { check } from 'k6';

const albUrl = __ENV.ALB_URL;
if (!albUrl) throw new Error('Pass the ALB origin with -e ALB_URL=http://...');

export const options = {
  scenarios: {
    product: {
      executor: 'ramping-arrival-rate',
      startRate: Number(__ENV.LOW_RATE),
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.VUS),
      stages: [
        { target: Number(__ENV.LOW_RATE), duration: __ENV.PRE_DURATION },
        { target: Number(__ENV.HIGH_RATE), duration: __ENV.RISE_DURATION },
        { target: Number(__ENV.HIGH_RATE), duration: __ENV.HIGH_DURATION },
        { target: Number(__ENV.LOW_RATE), duration: __ENV.FALL_DURATION },
        { target: Number(__ENV.LOW_RATE), duration: __ENV.POST_DURATION },
      ],
    },
  },
  maxRedirects: 0,
  thresholds: { checks: ['rate==1'] },
};

http.setResponseCallback(http.expectedStatuses(200));

export default function () {
  const response = http.get(`${albUrl.replace(/\/$/, '')}/productapi/products`, {
    timeout: '5s',
    redirects: 0,
  });
  check(response, { 'HTTP 200': (r) => r.status === 200 });
}
