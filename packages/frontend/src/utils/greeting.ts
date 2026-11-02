/**
 * Start-screen greetings.
 *
 * The greeting is chosen once per mount. It is either one of the approved
 * phrases below or the current time-of-day greeting (morning/afternoon/
 * evening). No other variants are used.
 */

const GREETINGS = [
  'Hello! How can I help?',
  'Hi! What’s on your mind?',
  'Hey! What are we working on?',
  'Welcome! What do you need?',
  'Hi there! Got a task?',
  'Ready when you are.',
  'What can I help with?',
  'Hello! Where should we start?',
  'Hey! What’s the plan?',
  'Hi! Let’s get to work.',
  'What are we tackling today?',
  'Hello! Need something done?',
  'Hey there! What’s first?',
  'Hi! Got a question?',
  'Welcome back! What’s next?',
  'What would you like to get done?',
  'Hello! Drop in your task.',
  'Hi! Let’s build something.',
  'Hey! Paste it here.',
  'Good to see you. What’s up?',
  'Hello! What’s the goal?',
  'Hi! Tell me what you need.',
  'Got a problem? Let’s solve it.',
  'Hey! Let’s make progress.',
  'Hello! What’s on your list?',
  'Hi! Where do we begin?',
  'Ready to start? Just ask.',
  'Hey! What should we fix?',
  'Hello! Let’s get going.',
  'Hi there! What’s the task?',
];

function timeOfDayGreeting(name: string, now: Date): string {
  const hour = now.getHours();
  const part =
    hour >= 5 && hour < 12
      ? 'Good morning'
      : hour >= 12 && hour < 17
        ? 'Good afternoon'
        : 'Good evening';
  return name ? `${part}, ${name}.` : `${part}.`;
}

export function getGreeting(name: string, now: Date = new Date()): string {
  const pool = [...GREETINGS, timeOfDayGreeting(name, now)];
  return pool[Math.floor(Math.random() * pool.length)];
}
