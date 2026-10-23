import http from 'k6/http';
import { check } from 'k6';

const albUrl = __ENV.ALB_URL;
if (!albUrl) throw new Error('Pass the ALB origin with -e ALB_URL=http://...');

export const options = {
  scenarios: {
    product: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 1),
      timeUnit: '1s',
      duration: __ENV.DURATION || '10s',
      preAllocatedVUs: Number(__ENV.VUS || 2),
    },
  },
  maxRedirects: 0,
};

http.setResponseCallback(http.expectedStatuses(200));

export default function () {
  const response = http.get(`${albUrl.replace(/\/$/, '')}/productapi/products`, {
    timeout: '5s',
    redirects: 0,
  });
  check(response, { 'HTTP 200': (r) => r.status === 200 });
}
