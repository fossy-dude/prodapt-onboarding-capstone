"""Evaluation harness for the self-care chatbot (Story 5.2).

Lives at the ``service_webapp`` root (alongside ``src/``) on purpose: it mirrors
the Target State ``eval-service`` separation and keeps eval-only deps
(``deepeval``, ``openai``) out of the runtime ``lint``/``test`` gates. The
package is importable in both gates because ``PYTHONPATH`` includes the
service root (see ``[tool.pytest.ini_options].pythonpath``).
"""
