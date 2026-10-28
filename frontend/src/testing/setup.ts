import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { routes } from '../app/app.routes';
import { respondAll } from './api-fixtures';

/** Navigate the real router to a URL with every API call answered from fixtures. */
export async function renderRoute(url: string, overrides: Record<string, unknown> = {}) {
  TestBed.configureTestingModule({
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter(routes, withComponentInputBinding())],
  });
  const http = TestBed.inject(HttpTestingController);
  const harness = await RouterTestingHarness.create();
  const navigation = harness.navigateByUrl(url);
  for (let i = 0; i < 5; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    respondAll(http, overrides);
  }
  await navigation;
  respondAll(http, overrides);
  harness.detectChanges();
  await harness.fixture.whenStable();
  respondAll(http, overrides);
  harness.detectChanges();
  return { harness, http, el: harness.routeNativeElement as HTMLElement, root: harness.fixture.nativeElement as HTMLElement };
}

export function text(el: Element | null | undefined): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}
