// SYNTHETIC SAMPLE TESTS - not taken from any Conga repository.
package com.example.clm.ui;

import org.testng.annotations.Test;

public class ClauseLibraryTests extends BaseUiTest {

    @Test(groups = {"regression", "clauses"}, description = "Add an alternate clause to the clause library")
    public void addAlternateClause() {
        openClauseLibrary();
        addClause("Limitation of Liability", "alternate");
    }
}
