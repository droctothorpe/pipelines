// Copyright 2026 The Kubeflow Authors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

// THROWAWAY: compare three tab/canvas boundaries on existing graph routes via ?variant=.
import { HTMLAttributes, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';
import './GraphBoundaryPrototype.css';

const variants = [
  { key: 'original', name: 'Original', detail: 'Current tabs + 8px white strip' },
  { key: 'flush', name: 'Flush', detail: 'No gap · canvas meets the tab divider' },
  { key: 'inset', name: 'Inset canvas', detail: '12px frame · rounded canvas corners' },
  { key: 'floating', name: 'Floating tabs', detail: 'Tabs on the canvas · no full-width seam' },
];

interface Props extends HTMLAttributes<HTMLDivElement> {
  graphActive: boolean;
}

export default function GraphBoundaryPrototype({ graphActive, ...props }: Props) {
  if (process.env.NODE_ENV !== 'development') return <div {...props} />;
  return <DevelopmentPrototype graphActive={graphActive} {...props} />;
}

function DevelopmentPrototype({ graphActive, className, children, ...props }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const search = new URLSearchParams(location.search);
  const index = variants.findIndex((variant) => variant.key === search.get('variant'));
  const current = variants[index];

  function switchVariant(direction: number) {
    const next = variants[(index + direction + variants.length) % variants.length];
    const nextSearch = new URLSearchParams(location.search);
    nextSearch.set('variant', next.key);
    navigate({ ...location, search: nextSearch.toString() }, { replace: true });
  }

  // External sync: subscribe to browser keyboard events; leave canvas/input shortcuts alone.
  useEffect(() => {
    if (!current) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        target.closest('input, textarea, select, [contenteditable], [data-prototype-canvas]')
      ) {
        return;
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = variants[(index + direction + variants.length) % variants.length];
      const nextSearch = new URLSearchParams(location.search);
      nextSearch.set('variant', next.key);
      navigate({ ...location, search: nextSearch.toString() }, { replace: true });
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [current, index, location, navigate]);

  return (
    <div
      {...props}
      className={`${className || ''}${current ? ' graph-boundary-prototype' : ''}`}
      data-graph-variant={graphActive ? current?.key : undefined}
    >
      {children}
      {current && (
        <aside className='graph-prototype-switcher' aria-label='Graph boundary prototype'>
          <button aria-label='Previous variant' onClick={() => switchVariant(-1)}>
            ←
          </button>
          <div className='graph-prototype-label' aria-live='polite'>
            <small>
              DESIGN PROTOTYPE · {index + 1} / {variants.length}
            </small>
            <strong>{current.name}</strong>
            <span>{graphActive ? current.detail : 'Open the Graph tab to compare'}</span>
          </div>
          <button aria-label='Next variant' onClick={() => switchVariant(1)}>
            →
          </button>
        </aside>
      )}
    </div>
  );
}
