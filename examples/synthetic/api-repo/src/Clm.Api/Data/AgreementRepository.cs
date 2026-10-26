// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
namespace Clm.Api.Services
{
    public interface IAgreementRepository
    {
        Task<Agreement> GetAsync(string id);
        Task<Agreement> SaveAsync(Agreement agreement);
    }

    public class Agreement
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Status { get; set; }
        public DateTime EndDate { get; set; }
        public bool Indexed { get; set; }
    }

    public class RenewRequest
    {
        public int? TermMonths { get; set; }
    }

    public class AgreementRequest
    {
        public string Name { get; set; }
    }
}
