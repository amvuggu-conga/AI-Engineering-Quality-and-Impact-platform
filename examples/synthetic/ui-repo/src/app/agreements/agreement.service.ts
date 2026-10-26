// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class AgreementService {
  constructor(private http: HttpClient) {}

  renewAgreement(id: string, termMonths: number) {
    return this.http.post(`/api/clm/v1/agreements/${id}/renew`, { termMonths });
  }

  activateAgreement(id: string) {
    return this.http.post(`/api/clm/v1/agreements/${id}/activate`, {});
  }
}
