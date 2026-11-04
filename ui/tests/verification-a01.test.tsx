import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { VerifyBlock } from '../src/events/VerifyBlock';
import { Footer } from '../src/events/Footer';

it('shows a no-test outcome as unverified rather than passed', () => {
  render(<><VerifyBlock event={{type:'verify.start', seq:1, ts:0, agent:'TEMPER', target:'workspace', status:'unverified'}} />
    <Footer event={{type:'run.done', seq:2, ts:0, steps:1, duration_s:1, status:'failed', verification_status:'unverified'}} /></>);
  expect(screen.getByText(/no test command found/i)).toBeTruthy();
  expect(screen.getByText('unverified')).toBeTruthy();
  expect(screen.queryByText(/passed/i)).toBeNull();
});
