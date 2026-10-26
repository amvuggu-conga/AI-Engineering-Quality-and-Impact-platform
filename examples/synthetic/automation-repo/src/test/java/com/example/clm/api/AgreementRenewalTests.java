// SYNTHETIC SAMPLE TESTS - not taken from any Conga repository.
package com.example.clm.api;

import org.testng.annotations.Test;

public class AgreementRenewalTests extends BaseApiTest {

    @Test(groups = {"regression", "renewal"}, description = "Renew an activated agreement with explicit term")
    public void renewActivatedAgreementWithTerm() {
        var agreement = createActivatedAgreement();
        var response = post("/api/clm/v1/agreements/" + agreement.id + "/renew", "{\"termMonths\": 24}");
        assertStatus(response, 200);
    }

    @Test(groups = {"regression", "renewal"}, description = "Renew uses default term when none provided")
    public void renewUsesDefaultTerm() {
        var agreement = createActivatedAgreement();
        var response = post("/api/clm/v1/agreements/" + agreement.id + "/renew", "{}");
        assertStatus(response, 200);
    }
}
