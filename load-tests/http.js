import http from 'k6/http';
import { check } from 'k6';

const url = __ENV.URL;
const rate = Number(__ENV.RATE);
const duration = __ENV.DURATION;
const vus = Number(__ENV.VUS || 10);

if (!url || !Number.isInteger(rate) || rate < 1 || !duration || !Number.isInteger(vus) || vus < 1) {
  throw new Error('Set URL, positive integer RATE, and DURATION; VUS is optional (default 10)');
}

export const options = {
  scenarios: {
    http_get: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration,
      preAllocatedVUs: vus,
    },
  },
  maxRedirects: 0,
};

http.setResponseCallback(http.expectedStatuses(200));

export default function () {
  const response = http.get(url, { timeout: '5s', redirects: 0 });
  check(response, { 'HTTP 200': (r) => r.status === 200 });
}
