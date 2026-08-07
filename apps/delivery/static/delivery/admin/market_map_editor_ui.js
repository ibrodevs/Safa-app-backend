(() => {
  'use strict';

  const status = document.getElementById('market-map-status');
  const modal = document.getElementById('market-map-error-modal');
  const messageNode = document.getElementById('market-map-error-message');
  const closeButton = document.getElementById('market-map-error-close');

  if (!status || !modal || !messageNode || !closeButton) return;

  let lastShownMessage = '';
  let restoreFocus = null;

  function friendlyMessage(raw) {
    const message = String(raw || '').trim();
    if (!message) return 'Произошла ошибка. Проверьте данные и попробуйте ещё раз.';

    const lower = message.toLowerCase();
    if (lower.includes('failed to fetch') || lower.includes('networkerror') || lower.includes('network error')) {
      return 'Не удалось связаться с сервером. Проверьте интернет-соединение и попробуйте ещё раз.';
    }
    if (lower.includes('csrf')) {
      return 'Сессия устарела. Обновите страницу и повторите действие.';
    }
    if (lower.includes('500') || lower.includes('internal server error')) {
      return 'Сервер не смог обработать карту. Попробуйте ещё раз. Если ошибка повторится — обратитесь к разработчику.';
    }
    return message;
  }

  function showError(rawMessage) {
    const message = friendlyMessage(rawMessage);
    if (!modal.hidden && message === lastShownMessage) return;

    lastShownMessage = message;
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    messageNode.textContent = message;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('market-map-modal-open');

    window.requestAnimationFrame(() => closeButton.focus());
  }

  function closeError() {
    if (modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('market-map-modal-open');
    lastShownMessage = '';

    if (restoreFocus && document.contains(restoreFocus)) {
      restoreFocus.focus();
    }
    restoreFocus = null;
  }

  // Public entry point for editor-side validations. MutationObserver below stays
  // as a fallback so every existing setStatus(..., 'error') also opens the modal.
  window.marketMapShowError = showError;

  function syncStatus() {
    if (!status.classList.contains('error')) return;
    const message = status.textContent.trim();
    if (message) showError(message);
  }

  const observer = new MutationObserver(syncStatus);
  observer.observe(status, {
    attributes: true,
    attributeFilter: ['class'],
    childList: true,
    characterData: true,
    subtree: true,
  });

  // Дополнительные настройки в редакторе карты всегда видимы.
  // Даже если браузер/Jazzmin попытается закрыть <details>, сразу открываем его обратно.
  document.querySelectorAll('details.market-map-advanced-fields').forEach((details) => {
    details.open = true;
    details.setAttribute('open', '');
    const summary = details.querySelector('summary');
    if (summary) {
      summary.setAttribute('aria-disabled', 'true');
      summary.setAttribute('tabindex', '-1');
    }
    details.addEventListener('toggle', () => {
      if (!details.open) {
        details.open = true;
        details.setAttribute('open', '');
      }
    });
  });

  // Район карты связан с тарифом через его название. Это сохраняет обратную
  // совместимость со старыми GeoJSON и позволяет тарифам работать без миграции.
  const districtTariff = document.getElementById('market-feature-district-tariff');
  const featureKind = document.getElementById('market-feature-kind');
  const featureName = document.getElementById('market-feature-name');
  const districtRows = Array.from(document.querySelectorAll('[data-kind-scope="district"]'));

  function selectedDistrictTariffName() {
    const option = districtTariff?.selectedOptions?.[0];
    if (!option || !districtTariff?.value) return '';
    return String(option.textContent || '').split(' — ')[0].trim();
  }

  function syncDistrictTariffUi() {
    const isDistrict = featureKind?.value === 'district';
    districtRows.forEach((row) => { row.hidden = !isDistrict; });
    if (!isDistrict || !districtTariff || !featureName) return;

    // При открытии уже существующего района восстанавливаем выбор тарифа по имени.
    const currentName = featureName.value.trim().toLocaleLowerCase('ru');
    if (!currentName || districtTariff.value) return;
    const matching = Array.from(districtTariff.options).find((option) => {
      if (!option.value) return false;
      const name = String(option.textContent || '').split(' — ')[0].trim().toLocaleLowerCase('ru');
      return name === currentName;
    });
    if (matching) districtTariff.value = matching.value;
  }

  districtTariff?.addEventListener('change', () => {
    const tariffName = selectedDistrictTariffName();
    if (tariffName && featureName) featureName.value = tariffName;
  });

  // Google Maps меняет выбранный feature не через обычный form change event,
  // поэтому лёгкая синхронизация нужна после взаимодействия с картой.
  document.addEventListener('click', () => window.setTimeout(syncDistrictTariffUi, 0), true);
  syncDistrictTariffUi();

  // Validate the most common admin mistakes before the main editor handler runs.
  // Capturing phase also copies the selected district tariff into the district
  // name before market_map_editor.js serializes the GeoJSON.
  document.addEventListener('click', (event) => {
    const action = event.target instanceof Element
      ? event.target.closest('#market-feature-apply, #market-map-save, #market-map-publish')
      : null;
    if (!action) return;

    if (featureKind?.value === 'district' && action.id === 'market-feature-apply') {
      const tariffName = selectedDistrictTariffName();
      if (tariffName && featureName) featureName.value = tariffName;
    }

    const passage = document.getElementById('market-feature-passage');
    if (featureKind?.value !== 'container' || passage?.value) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    showError('Для контейнера обязательно выберите проход.');
    window.setTimeout(() => passage?.focus(), 0);
  }, true);

  // Convert Django/Jazzmin validation messages on this editor page to the same modal.
  const djangoErrors = Array.from(document.querySelectorAll('.errornote, .errorlist'))
    .map((node) => node.textContent.trim())
    .filter(Boolean);
  if (djangoErrors.length) {
    showError(djangoErrors.join('\n'));
  }

  document.querySelectorAll('[data-market-map-error-close]').forEach((node) => {
    node.addEventListener('click', closeError);
  });
  closeButton.addEventListener('click', closeError);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) {
      event.preventDefault();
      closeError();
    }
  });

  // Если основной редактор успел записать ошибку до подключения этого файла.
  syncStatus();
})();