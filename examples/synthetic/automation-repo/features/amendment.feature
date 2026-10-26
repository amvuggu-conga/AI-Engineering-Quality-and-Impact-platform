# SYNTHETIC SAMPLE TESTS - not taken from any Conga repository.
@amend @regression
Feature: Agreement amendment

  @smoke
  Scenario: Amend an activated agreement
    Given an activated agreement exists
    When the user amends the agreement
    Then a new amendment version is created in Draft status

  Scenario: Renewal is blocked for terminated agreements
    Given a terminated agreement exists
    When the user tries to renew the agreement
    Then the renew action is rejected with a validation error
