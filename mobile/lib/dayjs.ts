import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

// dayjs with the plugins the app uses: relativeTime for "in 2 days".
dayjs.extend(relativeTime);

export default dayjs;
