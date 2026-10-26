// SYNTHETIC SAMPLE TESTS - not taken from any Conga repository.
package com.example.clm.api;

import org.testng.annotations.Test;

public class AgreementActivationTests extends BaseApiTest {

    @Test(groups = {"smoke", "activation"}, description = "Activate a fully signed agreement")
    public void activateFullySignedAgreement() {
        var agreement = createSignedAgreement();
        var response = post("/api/clm/v1/agreements/" + agreement.id + "/activate", "{}");
        assertStatus(response, 200);
    }
}
