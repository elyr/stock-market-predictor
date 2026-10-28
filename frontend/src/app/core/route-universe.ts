import { inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { Universe } from './models';

/** The dashboard (stocks or crypto) the current route belongs to. */
export function injectUniverse(): Universe {
  const route = inject(ActivatedRoute);
  for (const snapshot of [...route.snapshot.pathFromRoot].reverse()) {
    const universe = snapshot.data['universe'];
    if (universe) return universe as Universe;
  }
  return 'stocks';
}
