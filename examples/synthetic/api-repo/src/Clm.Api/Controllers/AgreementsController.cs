// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
using Clm.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Clm.Api.Controllers
{
    [ApiController]
    [Route("api/clm/v1/agreements")]
    public class AgreementsController : ControllerBase
    {
        private readonly IAgreementService _agreementService;
        private readonly IRenewalService _renewalService;

        public AgreementsController(IAgreementService agreementService, IRenewalService renewalService)
        {
            _agreementService = agreementService;
            _renewalService = renewalService;
        }

        [HttpGet("{id}")]
        public async Task<IActionResult> GetAgreement(string id)
        {
            return Ok(await _agreementService.GetAsync(id));
        }

        [HttpPost]
        public async Task<IActionResult> CreateAgreement([FromBody] AgreementRequest request)
        {
            return Ok(await _agreementService.CreateAsync(request));
        }

        [HttpPost("{id}/renew")]
        public async Task<IActionResult> RenewAgreement(string id, [FromBody] RenewRequest request)
        {
            return Ok(await _renewalService.RenewAsync(id, request));
        }

        [HttpPost("{id}/activate")]
        public async Task<IActionResult> ActivateAgreement(string id)
        {
            return Ok(await _agreementService.ActivateAsync(id));
        }
    }
}
